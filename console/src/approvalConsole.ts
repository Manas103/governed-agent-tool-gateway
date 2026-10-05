// A CLI approval console: lists every pending proposal with its oracle verdict, and
// approves or rejects one by id. Talks to a running `uvicorn gateway.gateway_app:app`
// instance; this is the thing a human approver would actually run.
import { GatewayClient } from "./client.js";

function printEntries(entries: Awaited<ReturnType<GatewayClient["listPendingApprovals"]>>): void {
  if (entries.length === 0) {
    console.log("No pending approvals.");
    return;
  }
  for (const entry of entries) {
    const flag = entry.oracle_ok ? "" : `  [ORACLE FLAGGED: ${entry.oracle_reason}]`;
    console.log(`${entry.approval_id}  ${entry.caller_group} -> ${entry.tool}(${JSON.stringify(entry.params)})${flag}`);
  }
}

async function main(): Promise<void> {
  const baseUrl = process.env.GATEWAY_URL ?? "http://127.0.0.1:8000";
  const client = new GatewayClient(baseUrl);
  const [command, arg1, arg2] = process.argv.slice(2);

  if (command === "list" || command === undefined) {
    printEntries(await client.listPendingApprovals());
    return;
  }
  if (command === "approve" || command === "reject") {
    if (!arg1) throw new Error(`usage: approvalConsole ${command} <approval_id>`);
    const result = await client.decide(arg1, command === "approve");
    console.log(`${result.approval_id} -> ${result.decision}`);
    return;
  }
  if (command === "registry") {
    console.log(JSON.stringify(await client.getRegistry(), null, 2));
    return;
  }
  throw new Error(`unknown command: ${command} ${arg1 ?? ""} ${arg2 ?? ""}`.trim());
}

main().catch((err: unknown) => {
  console.error(err instanceof Error ? err.message : err);
  process.exitCode = 1;
});
