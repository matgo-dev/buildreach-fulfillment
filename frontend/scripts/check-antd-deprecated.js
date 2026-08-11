const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..", "src");
const CHECKS = [
  {
    component: "Space",
    prop: "direction",
    replacement: "orientation",
    pattern: /<Space\b(?:(?!\/?>)[\s\S])*\bdirection\s*=/g,
  },
  {
    component: "Modal",
    prop: "destroyOnClose",
    replacement: "destroyOnHidden",
    pattern: /<Modal\b(?:(?!\/?>)[\s\S])*\bdestroyOnClose\s*=/g,
  },
  {
    component: "Drawer",
    prop: "width",
    replacement: "size",
    pattern: /<Drawer\b(?:(?!\/?>)[\s\S])*\bwidth\s*=/g,
  },
  {
    component: "Modal/Drawer",
    prop: "visible",
    replacement: "open",
    pattern: /<(?:Modal|Drawer)\b(?:(?!\/?>)[\s\S])*\bvisible\s*=/g,
  },
];

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return walk(full);
    return /\.(tsx|ts)$/.test(entry.name) ? [full] : [];
  });
}

function lineOf(source, index) {
  return source.slice(0, index).split("\n").length;
}

const findings = [];
for (const file of walk(ROOT)) {
  const source = fs.readFileSync(file, "utf8");
  for (const check of CHECKS) {
    for (const match of source.matchAll(check.pattern)) {
      findings.push({
        file: path.relative(path.join(__dirname, ".."), file),
        line: lineOf(source, match.index || 0),
        check,
      });
    }
  }
}

if (findings.length > 0) {
  console.error("Ant Design deprecated props found:");
  for (const item of findings) {
    console.error(
      `- ${item.file}:${item.line} <${item.check.component}> ${item.check.prop} is deprecated; use ${item.check.replacement}.`,
    );
  }
  process.exit(1);
}

