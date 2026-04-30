// Symbol + parameter/return-type extraction.

import * as path from "path";
import * as ts from "typescript";
import { SemanticSymbol, SemanticTypeFact } from "./protocol";

export interface ExtractedSymbols {
  symbols: SemanticSymbol[];
  types: SemanticTypeFact[];
  byNode: Map<ts.Node, SemanticSymbol>;
}

export function extractSymbols(
  source: ts.SourceFile,
  checker: ts.TypeChecker,
  repoRoot: string,
): ExtractedSymbols {
  const relPath = toRel(source.fileName, repoRoot);
  const symbols: SemanticSymbol[] = [];
  const types: SemanticTypeFact[] = [];
  const byNode = new Map<ts.Node, SemanticSymbol>();

  function visit(node: ts.Node, parentQname: string | null): void {
    const handled = visitContainer(node, parentQname);
    ts.forEachChild(node, (child) => visit(child, handled ?? parentQname));
  }

  function visitContainer(node: ts.Node, parentQname: string | null): string | null {
    if (ts.isFunctionDeclaration(node) && node.name) {
      const sym = makeSymbol(node, "function", node.name.text, parentQname);
      symbols.push(sym);
      byNode.set(node, sym);
      collectParamAndReturn(node, sym);
      return sym.qualified_name;
    }
    if (ts.isClassDeclaration(node) && node.name) {
      const sym = makeSymbol(node, "class", node.name.text, parentQname);
      symbols.push(sym);
      byNode.set(node, sym);
      for (const member of node.members) {
        if (
          (ts.isMethodDeclaration(member) || ts.isConstructorDeclaration(member)) &&
          member.body
        ) {
          const memberName = ts.isConstructorDeclaration(member)
            ? "constructor"
            : (member.name as ts.Identifier).text;
          const kind = ts.isConstructorDeclaration(member) ? "constructor" : "method";
          const memberSym = makeSymbol(member, kind, memberName, sym.qualified_name);
          symbols.push(memberSym);
          byNode.set(member, memberSym);
          collectParamAndReturn(member, memberSym);
        } else if (ts.isPropertyDeclaration(member) && member.name) {
          const propName = (member.name as ts.Identifier).text;
          const propSym = makeSymbol(member, "property", propName, sym.qualified_name);
          symbols.push(propSym);
          byNode.set(member, propSym);
          const declared = member.type ? member.type.getText(source) : "";
          const inferred = describeType(checker, member);
          types.push({
            owner_symbol: sym.qualified_name,
            name: propName,
            kind: "field",
            declared_type: declared,
            inferred_type: inferred,
          });
        }
      }
      return sym.qualified_name;
    }
    if (ts.isInterfaceDeclaration(node)) {
      const sym = makeSymbol(node, "interface", node.name.text, parentQname);
      symbols.push(sym);
      byNode.set(node, sym);
      for (const member of node.members) {
        if (
          (ts.isPropertySignature(member) || ts.isMethodSignature(member)) &&
          member.name
        ) {
          const propName = (member.name as ts.Identifier).text;
          const declared = member.type ? member.type.getText(source) : "";
          types.push({
            owner_symbol: sym.qualified_name,
            name: propName,
            kind: ts.isMethodSignature(member) ? "method" : "field",
            declared_type: declared,
            inferred_type: declared,
          });
        }
      }
      return sym.qualified_name;
    }
    if (ts.isTypeAliasDeclaration(node)) {
      const sym = makeSymbol(node, "type_alias", node.name.text, parentQname);
      sym.return_type = node.type.getText(source);
      symbols.push(sym);
      byNode.set(node, sym);
      return sym.qualified_name;
    }
    if (ts.isEnumDeclaration(node)) {
      const sym = makeSymbol(node, "enum", node.name.text, parentQname);
      symbols.push(sym);
      byNode.set(node, sym);
      return sym.qualified_name;
    }
    if (ts.isVariableStatement(node)) {
      // Capture top-level arrow / function-expression assignments.
      for (const decl of node.declarationList.declarations) {
        if (!decl.name || !ts.isIdentifier(decl.name)) continue;
        const init = decl.initializer;
        if (
          init &&
          (ts.isArrowFunction(init) || ts.isFunctionExpression(init))
        ) {
          const sym = makeSymbol(decl, "function", decl.name.text, parentQname);
          symbols.push(sym);
          byNode.set(init, sym);
          byNode.set(decl, sym);
          collectParamAndReturn(init, sym);
        } else if (decl.type) {
          const sym = makeSymbol(decl, "variable", decl.name.text, parentQname);
          sym.return_type = decl.type.getText(source);
          symbols.push(sym);
          byNode.set(decl, sym);
        }
      }
    }
    return null;
  }

  function makeSymbol(
    node: ts.Node,
    kind: string,
    name: string,
    parentQname: string | null,
  ): SemanticSymbol {
    const start = source.getLineAndCharacterOfPosition(node.getStart(source));
    const end = source.getLineAndCharacterOfPosition(node.getEnd());
    const qname = parentQname ? `${parentQname}.${name}` : `${qnameForFile(relPath)}.${name}`;
    let signature = "";
    let returnType = "";
    if (
      ts.isFunctionDeclaration(node) ||
      ts.isMethodDeclaration(node) ||
      ts.isConstructorDeclaration(node)
    ) {
      signature = formatSignature(node, source, checker);
      returnType = describeReturnType(checker, node);
    } else if (
      (ts.isVariableDeclaration(node) ||
        ts.isArrowFunction(node) ||
        ts.isFunctionExpression(node)) &&
      "type" in node &&
      node.type
    ) {
      returnType = (node.type as ts.TypeNode).getText(source);
    }
    return {
      id: `${relPath}::${qname}`,
      name,
      kind,
      qualified_name: qname,
      signature,
      return_type: returnType,
      start_line: start.line + 1,
      end_line: end.line + 1,
    };
  }

  function collectParamAndReturn(
    node: ts.SignatureDeclaration,
    owner: SemanticSymbol,
  ): void {
    for (const param of node.parameters) {
      if (!param.name || !ts.isIdentifier(param.name)) continue;
      const declared = param.type ? param.type.getText(source) : "";
      const inferred = declared || describeType(checker, param);
      types.push({
        owner_symbol: owner.qualified_name,
        name: param.name.text,
        kind: "parameter",
        declared_type: declared,
        inferred_type: inferred,
      });
    }
    if (owner.return_type) {
      types.push({
        owner_symbol: owner.qualified_name,
        name: "(return)",
        kind: "return",
        declared_type: owner.return_type,
        inferred_type: owner.return_type,
      });
    }
  }

  visit(source, null);
  return { symbols, types, byNode };
}

export function qnameForFile(relPath: string): string {
  const noExt = relPath.replace(/\.(ts|tsx|js|jsx|mjs|cjs)$/i, "");
  return noExt.split(/[\\/]/).filter(Boolean).join(".");
}

export function toRel(filePath: string, repoRoot: string): string {
  const rel = path.relative(repoRoot, filePath);
  return rel.split(path.sep).join("/");
}

function formatSignature(
  node: ts.SignatureDeclaration,
  source: ts.SourceFile,
  checker: ts.TypeChecker,
): string {
  const params = node.parameters
    .map((p) => p.getText(source))
    .join(", ");
  const ret = describeReturnType(checker, node);
  const name = node.name && ts.isIdentifier(node.name) ? node.name.text : "";
  return `${name}(${params})${ret ? `: ${ret}` : ""}`;
}

function describeReturnType(checker: ts.TypeChecker, node: ts.SignatureDeclaration): string {
  if (node.type) {
    return node.type.getText();
  }
  const sig = checker.getSignatureFromDeclaration(node);
  if (!sig) return "";
  const ret = checker.getReturnTypeOfSignature(sig);
  return checker.typeToString(ret);
}

function describeType(checker: ts.TypeChecker, node: ts.Node): string {
  try {
    const t = checker.getTypeAtLocation(node);
    return checker.typeToString(t);
  } catch {
    return "";
  }
}
