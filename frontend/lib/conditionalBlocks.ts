import type { DocManifest, RequiredWhenCondition } from "@/lib/docManifest";
import {
  CONDITION_OPERATORS,
  singleConditionMatches,
} from "@/lib/draftState";

const WHEN_RE = /^\s*<!--\s*when\s+(.+?)\s*-->\s*$/;
const ENDWHEN_RE = /^\s*<!--\s*endwhen\s*-->\s*$/;
const CONDITIONAL_OPS = new Set<string>(CONDITION_OPERATORS);

export class ConditionalTemplateError extends Error {}

export function applyConditionalBlocks(
  source: string,
  manifest: DocManifest,
  stableValues: Record<string, string>,
): string {
  const manifestKeys = new Set(manifest.fields.map((field) => field.key));
  const lines = source.match(/.*(?:\r\n|\n|$)/g)?.filter(Boolean) ?? [];
  const output: string[] = [];
  let active: { include: boolean; line: number } | null = null;

  for (const [index, line] of lines.entries()) {
    const lineNumber = index + 1;
    const marker = line.replace(/(?:\r\n|\n)$/, "");
    const when = marker.match(WHEN_RE);
    if (when) {
      if (active) {
        throw new ConditionalTemplateError(
          `Conditional blocks cannot be nested (line ${lineNumber}).`,
        );
      }
      const condition = parseCondition(when[1], manifestKeys, lineNumber);
      const isConfirmed = Object.hasOwn(stableValues, condition.field);
      active = {
        include:
          !isConfirmed || singleConditionMatches(condition, stableValues),
        line: lineNumber,
      };
      continue;
    }
    if (ENDWHEN_RE.test(marker)) {
      if (!active) {
        throw new ConditionalTemplateError(
          `Conditional end marker has no opening marker (line ${lineNumber}).`,
        );
      }
      active = null;
      continue;
    }
    const stripped = marker.trim();
    if (stripped.startsWith("<!-- when") || stripped.startsWith("<!-- endwhen")) {
      throw new ConditionalTemplateError(
        `Malformed conditional marker at line ${lineNumber}.`,
      );
    }
    if (!active || active.include) output.push(line);
  }

  if (active) {
    throw new ConditionalTemplateError(
      `Conditional block opened at line ${active.line} is not closed.`,
    );
  }
  return output.join("");
}

function parseCondition(
  payload: string,
  manifestKeys: Set<string>,
  lineNumber: number,
): RequiredWhenCondition {
  let raw: unknown;
  try {
    raw = JSON.parse(payload);
  } catch {
    throw new ConditionalTemplateError(
      `Conditional marker at line ${lineNumber} contains invalid JSON.`,
    );
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new ConditionalTemplateError(
      `Conditional marker at line ${lineNumber} must contain an object.`,
    );
  }
  const condition = raw as RequiredWhenCondition;
  if (
    typeof condition.field !== "string" ||
    condition.field.trim() === "" ||
    !manifestKeys.has(condition.field)
  ) {
    throw new ConditionalTemplateError(
      `Conditional marker at line ${lineNumber} references unknown manifest field.`,
    );
  }
  const rawRecord = raw as Record<string, unknown>;
  const op = Object.hasOwn(rawRecord, "op") ? rawRecord.op : "equals";
  if (typeof op !== "string" || !CONDITIONAL_OPS.has(op)) {
    throw new ConditionalTemplateError(
      `Conditional marker at line ${lineNumber} uses unsupported operator.`,
    );
  }
  if (
    (op === "equals" || op === "not_equals") &&
    typeof condition.value !== "string"
  ) {
    throw new ConditionalTemplateError(
      `Conditional marker at line ${lineNumber} requires a string value.`,
    );
  }
  if (
    op === "in" &&
    (!Array.isArray(condition.values) ||
      condition.values.length === 0 ||
      !condition.values.every((value) => typeof value === "string"))
  ) {
    throw new ConditionalTemplateError(
      `Conditional marker at line ${lineNumber} requires string values.`,
    );
  }
  return { ...condition, op: op as RequiredWhenCondition["op"] };
}
