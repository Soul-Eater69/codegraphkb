// Reference extraction: CALLS + ACCESSES via TypeChecker.

import * as ts from "typescript";
import { SemanticReference, SemanticSymbol } from "./protocol";
import { ExtractedSymbols, qnameForFile, toRel } from "./symbols";

export function extractReferences(
  source: ts.SourceFile,
  checker: ts.TypeChecker,
  repoRoot: string,
  extracted: ExtractedSymbols,
): SemanticReference[] {
  const out: SemanticReference[] = [];
  const fileQname = qnameForFile(toRel(source.fileName, repoRoot));

  // Track the enclosing symbol stack to attribute references.
  const stack: SemanticSymbol[] = [];

  function pushIfOwner(node: ts.Node): boolean {
    const owner = extracted.byNode.get(node);
    if (owner) {
      stack.push(owner);
      return true;
    }
    return false;
  }

  function visit(node: ts.Node): void {
    const pushed = pushIfOwner(node);
    if (ts.isCallExpression(node)) {
      handleCall(node);
    } else if (ts.isPropertyAccessExpression(node)) {
      handleAccess(node);
    }
    ts.forEachChild(node, visit);
    if (pushed) stack.pop();
  }

  function currentOwner(): string {
    return stack.length > 0 ? stack[stack.length - 1].qualified_name : `${fileQname}.<module>`;
  }

  function handleCall(node: ts.CallExpression): void {
    const fromSymbol = currentOwner();
    const callee = node.expression;
    let target: ts.Symbol | undefined;
    let receiverType: string | null = null;
    let callForm = "free";
    let calleeName = "";

    if (ts.isPropertyAccessExpression(callee)) {
      callForm = "method";
      calleeName = callee.name.text;
      try {
        const recvType = checker.getTypeAtLocation(callee.expression);
        receiverType = checker.typeToString(recvType);
        const prop = checker.getPropertyOfType(recvType, calleeName);
        if (prop) target = prop;
      } catch {
        /* ignore */
      }
      if (!target) {
        try {
          target = checker.getSymbolAtLocation(callee.name);
        } catch {
          /* ignore */
        }
      }
    } else if (ts.isIdentifier(callee)) {
      calleeName = callee.text;
      try {
        target = checker.getSymbolAtLocation(callee);
      } catch {
        /* ignore */
      }
    } else {
      calleeName = callee.getText(source);
    }

    target = followAlias(target, checker);
    const resolved = target ? declaredQname(target, repoRoot) : null;
    out.push({
      from_symbol: fromSymbol,
      to_symbol: resolved,
      edge_type: "CALLS",
      receiver_type: receiverType,
      call_form: callForm,
      confidence: resolved ? 0.94 : 0.7,
      precision_level: 3,
      reason: resolved
        ? "TypeChecker resolved target symbol"
        : `TypeChecker could not resolve callee \`${calleeName}\``,
    });
  }

  function handleAccess(node: ts.PropertyAccessExpression): void {
    // Skip the property access at the head of a call expression — that's
    // already captured as a CALLS edge.
    if (node.parent && ts.isCallExpression(node.parent) && node.parent.expression === node) {
      return;
    }
    const fromSymbol = currentOwner();
    let target: ts.Symbol | undefined;
    let receiverType: string | null = null;
    try {
      const recvType = checker.getTypeAtLocation(node.expression);
      receiverType = checker.typeToString(recvType);
      const prop = checker.getPropertyOfType(recvType, node.name.text);
      if (prop) target = prop;
    } catch {
      /* ignore */
    }
    target = followAlias(target, checker);
    const resolved = target ? declaredQname(target, repoRoot) : null;
    out.push({
      from_symbol: fromSymbol,
      to_symbol: resolved,
      edge_type: "ACCESSES",
      receiver_type: receiverType,
      call_form: "property",
      confidence: resolved ? 0.88 : 0.6,
      precision_level: 3,
      reason: resolved
        ? "TypeChecker resolved property"
        : `TypeChecker could not resolve property \`${node.name.text}\``,
    });
  }

  visit(source);
  return out;
}

function followAlias(
  symbol: ts.Symbol | undefined,
  checker: ts.TypeChecker,
): ts.Symbol | undefined {
  if (!symbol) return undefined;
  let current = symbol;
  // Follow import/export aliases up to 8 hops (defensive cap).
  for (let i = 0; i < 8; i++) {
    if ((current.flags & ts.SymbolFlags.Alias) === 0) return current;
    try {
      const next = checker.getAliasedSymbol(current);
      if (!next || next === current) return current;
      current = next;
    } catch {
      return current;
    }
  }
  return current;
}

function declaredQname(symbol: ts.Symbol, repoRoot: string): string | null {
  const decls = symbol.declarations;
  if (!decls || decls.length === 0) return null;
  const decl = decls[0];
  const sf = decl.getSourceFile();
  if (sf.isDeclarationFile) return null;
  const rel = toRel(sf.fileName, repoRoot);
  // Walk up to find the nearest named declaration we can fingerprint.
  const parts: string[] = [];
  let node: ts.Node | undefined = decl;
  while (node && !ts.isSourceFile(node)) {
    const name = nodeName(node);
    if (name) parts.unshift(name);
    node = node.parent;
  }
  if (parts.length === 0) return null;
  return [qnameForFile(rel), ...parts].join(".");
}

function nodeName(node: ts.Node): string | null {
  if (
    (ts.isFunctionDeclaration(node) ||
      ts.isClassDeclaration(node) ||
      ts.isInterfaceDeclaration(node) ||
      ts.isTypeAliasDeclaration(node) ||
      ts.isEnumDeclaration(node)) &&
    node.name
  ) {
    return node.name.text;
  }
  if (ts.isMethodDeclaration(node) || ts.isPropertyDeclaration(node)) {
    if (node.name && ts.isIdentifier(node.name)) return node.name.text;
  }
  if (ts.isConstructorDeclaration(node)) return "constructor";
  if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) {
    return node.name.text;
  }
  return null;
}
