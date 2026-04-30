#!/usr/bin/env node
// Helper entry point. Usage:
//   node dist/index.js --repo /path/to/repo [--json]

import * as path from "path";
import { loadProject } from "./project";
import { extractSymbols, toRel } from "./symbols";
import { extractReferences } from "./references";
import {
  ADAPTER_VERSION,
  SemanticFileResult,
  SemanticResult,
} from "./protocol";

interface CliArgs {
  repo: string;
  json: boolean;
}

function parseArgs(argv: string[]): CliArgs {
  let repo = process.cwd();
  let json = false;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--repo" && i + 1 < argv.length) {
      repo = argv[++i];
    } else if (a === "--json") {
      json = true;
    } else if (a === "--version") {
      console.log(ADAPTER_VERSION);
      process.exit(0);
    } else if (a === "--help" || a === "-h") {
      printHelp();
      process.exit(0);
    }
  }
  return { repo, json };
}

function printHelp(): void {
  console.error(
    [
      "codegraphkb-ts-semantic — TypeScript Compiler API helper",
      "",
      "Usage:",
      "  codegraphkb-ts-semantic --repo <path> [--json]",
      "",
      "Emits SemanticResult JSON on stdout.",
    ].join("\n"),
  );
}

function main(): void {
  const args = parseArgs(process.argv.slice(2));
  const absRepo = path.resolve(args.repo);
  const project = loadProject(absRepo);
  const fileResults: SemanticFileResult[] = [];

  for (const source of project.sourceFiles) {
    const rel = toRel(source.fileName, absRepo);
    const extracted = extractSymbols(source, project.checker, absRepo);
    const refs = extractReferences(source, project.checker, absRepo, extracted);
    fileResults.push({
      path: rel,
      symbols: extracted.symbols,
      references: refs,
      types: extracted.types,
    });
  }

  const result: SemanticResult = {
    language: "typescript",
    adapter: "typescript-compiler-api",
    adapter_version: ADAPTER_VERSION,
    repo_path: absRepo,
    files: fileResults,
    diagnostics: [],
  };

  process.stdout.write(JSON.stringify(result));
  if (!args.json) process.stdout.write("\n");
}

try {
  main();
} catch (err) {
  const msg = err instanceof Error ? err.stack || err.message : String(err);
  process.stderr.write(`ts-semantic helper failed: ${msg}\n`);
  process.exit(1);
}
