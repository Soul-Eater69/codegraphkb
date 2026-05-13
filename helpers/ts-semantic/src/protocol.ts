// JSON contract emitted by the helper. Mirrors codegraphkb.core.semantic.protocol.

export interface SemanticParameter {
  owner_symbol: string;
  name: string;
  position: number;
  declared_type: string;
  inferred_type: string;
  default_value: string;
  is_optional: boolean;
  is_variadic: boolean;
  confidence: number;
}

export interface SemanticSymbol {
  id: string;
  name: string;
  kind: string;
  qualified_name: string;
  signature: string;
  return_type: string;
  start_line: number;
  end_line: number;
  parameters: SemanticParameter[];
}

export interface SemanticReference {
  from_symbol: string;
  to_symbol: string | null;
  edge_type: string;
  receiver_type: string | null;
  call_form: string;
  confidence: number;
  precision_level: number;
  reason: string;
}

export interface SemanticTypeFact {
  owner_symbol: string;
  name: string;
  kind: string;
  declared_type: string;
  inferred_type: string;
}

export interface SemanticFileResult {
  path: string;
  symbols: SemanticSymbol[];
  references: SemanticReference[];
  types: SemanticTypeFact[];
}

export interface SemanticResult {
  language: "typescript";
  adapter: "typescript-compiler-api";
  adapter_version: string;
  repo_path: string;
  files: SemanticFileResult[];
  diagnostics: Array<Record<string, unknown>>;
}

export const ADAPTER_VERSION = "0.2.0";
