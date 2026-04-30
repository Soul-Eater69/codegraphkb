// Locate tsconfig/jsconfig and build a TypeScript Program.

import * as fs from "fs";
import * as path from "path";
import * as ts from "typescript";

export interface LoadedProject {
  program: ts.Program;
  checker: ts.TypeChecker;
  rootDir: string;
  configPath: string | null;
  sourceFiles: ts.SourceFile[];
}

export function loadProject(repoPath: string): LoadedProject {
  const absRepo = path.resolve(repoPath);
  const configPath = findConfig(absRepo);
  let program: ts.Program;
  let rootDir = absRepo;

  if (configPath) {
    const cfgFile = ts.readConfigFile(configPath, ts.sys.readFile);
    if (cfgFile.error) {
      throw new Error(
        `Failed to read ${configPath}: ${ts.flattenDiagnosticMessageText(cfgFile.error.messageText, "\n")}`,
      );
    }
    const parsed = ts.parseJsonConfigFileContent(
      cfgFile.config ?? {},
      ts.sys,
      path.dirname(configPath),
    );
    program = ts.createProgram({
      rootNames: parsed.fileNames,
      options: parsed.options,
    });
    rootDir = parsed.options.rootDir
      ? path.resolve(path.dirname(configPath), parsed.options.rootDir)
      : path.dirname(configPath);
  } else {
    // No tsconfig: walk repo for .ts/.tsx/.js/.jsx files (best effort).
    const files = collectFiles(absRepo);
    program = ts.createProgram({
      rootNames: files,
      options: {
        target: ts.ScriptTarget.ES2020,
        module: ts.ModuleKind.CommonJS,
        allowJs: true,
        checkJs: false,
        esModuleInterop: true,
        skipLibCheck: true,
        noEmit: true,
        jsx: ts.JsxEmit.React,
      },
    });
  }

  const sourceFiles = program
    .getSourceFiles()
    .filter((f) => !f.isDeclarationFile)
    .filter((f) => isInsideRoot(f.fileName, absRepo));

  return {
    program,
    checker: program.getTypeChecker(),
    rootDir,
    configPath,
    sourceFiles,
  };
}

function findConfig(dir: string): string | null {
  for (const name of ["tsconfig.json", "jsconfig.json"]) {
    const candidate = path.join(dir, name);
    if (fs.existsSync(candidate)) return candidate;
  }
  return null;
}

function isInsideRoot(filePath: string, root: string): boolean {
  const norm = path.resolve(filePath);
  const base = path.resolve(root) + path.sep;
  return norm === path.resolve(root) || norm.startsWith(base);
}

const SRC_EXTS = new Set([".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]);
const SKIP_DIRS = new Set(["node_modules", ".git", "dist", "build", "out", ".next", ".turbo"]);

function collectFiles(root: string): string[] {
  const out: string[] = [];
  const stack = [root];
  while (stack.length > 0) {
    const dir = stack.pop()!;
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      if (entry.name.startsWith(".") && entry.name !== "." && entry.name !== "..") {
        if (SKIP_DIRS.has(entry.name)) continue;
      }
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (SKIP_DIRS.has(entry.name)) continue;
        stack.push(full);
      } else if (entry.isFile()) {
        const ext = path.extname(entry.name);
        if (SRC_EXTS.has(ext) && !entry.name.endsWith(".d.ts")) {
          out.push(full);
        }
      }
    }
  }
  return out;
}
