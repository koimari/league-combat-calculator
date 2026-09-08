import { build } from "esbuild";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
process.chdir(fileURLToPath(new URL(".", import.meta.url)));
const result = await build({
  absWorkingDir: fileURLToPath(new URL(".", import.meta.url)),
  entryPoints: ["src/standalone.tsx"],
  bundle: true,
  minify: true,
  format: "esm",
  target: ["es2022"],
  outdir: "../static/calculator",
  entryNames: "calculator",
  legalComments: "external",
  define: { "process.env.NODE_ENV": '"production"' },
  write: false,
});
const check = process.argv.includes("--check");
result.outputFiles.push({
  path: fileURLToPath(
    new URL("../static/calculator/favicon.svg", import.meta.url),
  ),
  contents: await readFile(new URL("assets/favicon.svg", import.meta.url)),
});
for (const file of result.outputFiles) {
  if (check) {
    const current = await readFile(file.path);
    if (!current.equals(Buffer.from(file.contents)))
      throw new Error(`Generated asset differs: ${file.path}`);
  } else {
    await mkdir(new URL("../static/calculator/", import.meta.url), {
      recursive: true,
    });
    await writeFile(file.path, file.contents);
  }
}
console.log(
  check ? "Calculator assets match source." : "Calculator assets built.",
);
