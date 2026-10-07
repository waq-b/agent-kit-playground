// Runs ../scripts/dump_openapi.py with the project's virtualenv Python if one
// exists (POSIX or Windows layout), otherwise whatever python is on PATH.
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const candidates = [
  join(root, ".venv", "bin", "python"),
  join(root, ".venv", "Scripts", "python.exe"),
];
const python = candidates.find(existsSync) ?? (process.platform === "win32" ? "python" : "python3");
const result = spawnSync(python, [join(root, "scripts", "dump_openapi.py")], { stdio: "inherit" });
process.exit(result.status ?? 1);
