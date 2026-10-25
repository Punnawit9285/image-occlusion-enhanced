// Browser test of the tap-to-reveal script. Run by tests/test_tapreveal_browser.py
// with: node tests/js/tapreveal.test.js <script.html> <mask.svg> <workdir>
const fs = require("fs");
const http = require("http");
const path = require("path");
const { chromium } = require("playwright");

const [scriptFile, maskFile, workdir] = process.argv.slice(2);
const script = fs.readFileSync(scriptFile, "utf8");
fs.copyFileSync(maskFile, path.join(workdir, "mask.svg"));
fs.writeFileSync(
  path.join(workdir, "image.svg"),
  '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#ddd"/></svg>'
);
fs.writeFileSync(
  path.join(workdir, "empty.svg"),
  '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><g><title>Masks</title></g></svg>'
);

function card(mask) {
  // the parts of the card template the script relies on, as in template.py
  return `<!doctype html><html><head><style>
    #io-overlay { position:absolute; top:0; width:100%; z-index:3 }
    #io-original { position:relative; top:0; width:100%; z-index:2 }
    #io-wrapper { position:relative; width:100% }
    img { max-width: 100%; }
  </style></head><body style="width:500px">
  <div id="io-wrapper"><div id="io-overlay"><img src="${mask}"></div>
  <div id="io-original"><img src="image.svg"></div></div>
  ${script}</body></html>`;
}

const results = {};
const server = http.createServer((req, res) => {
  const name = decodeURIComponent(req.url.split("?")[0].slice(1));
  if (name.startsWith("card-")) {
    res.setHeader("Content-Type", "text/html");
    return res.end(card(name.slice(5)));
  }
  const file = path.join(workdir, name);
  if (!fs.existsSync(file)) { res.statusCode = 404; return res.end("missing"); }
  res.setHeader("Content-Type", "image/svg+xml");
  res.end(fs.readFileSync(file));
});

const probe = () => {
  const layer = document.querySelector(".io-tap-layer");
  const img = document.querySelector("#io-overlay img");
  if (!layer) return { layer: false, imgVisible: img.style.visibility !== "hidden" };
  const l = layer.getBoundingClientRect(), i = img.getBoundingClientRect();
  return {
    layer: true,
    masks: layer.querySelectorAll(".io-mask").length,
    revealed: layer.querySelectorAll(".io-revealed").length,
    aligned: [l.left - i.left, l.top - i.top, l.width - i.width, l.height - i.height].every((d) => Math.abs(d) < 0.5),
    imgVisible: img.style.visibility !== "hidden",
  };
};

(async () => {
  await new Promise((r) => server.listen(0, r));
  const base = `http://127.0.0.1:${server.address().port}/`;
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));

  await page.goto(base + "card-mask.svg");
  await page.waitForTimeout(500);
  results.loaded = await page.evaluate(probe);
  const box = await page.evaluate(() => {
    const r = document.querySelector(".io-tap-layer .io-mask").getBoundingClientRect();
    return [r.left + r.width / 2, r.top + r.height / 2];
  });
  await page.mouse.click(box[0], box[1]);
  results.clicked = await page.evaluate(probe);
  await page.mouse.click(box[0], box[1]);
  results.clickedTwice = await page.evaluate(probe);
  // hide and show the masks, as the card's Toggle Masks button does
  await page.evaluate(() => (document.getElementById("io-overlay").style.display = "none"));
  await page.waitForTimeout(100);
  await page.evaluate(() => (document.getElementById("io-overlay").style.display = "block"));
  await page.waitForTimeout(200);
  results.toggled = await page.evaluate(probe);
  await page.setViewportSize({ width: 400, height: 400 });
  await page.evaluate(() => (document.body.style.width = "300px"));
  await page.waitForTimeout(300);
  results.resized = await page.evaluate(probe);

  await page.goto(base + "card-missing.svg");
  await page.waitForTimeout(500);
  results.missing = await page.evaluate(probe);

  await page.goto(base + "card-empty.svg");
  await page.waitForTimeout(500);
  results.noMasks = await page.evaluate(probe);

  fs.writeFileSync(path.join(workdir, "card.html"), card("mask.svg"));
  await page.goto("file://" + path.join(workdir, "card.html"));
  await page.waitForTimeout(500);
  results.fileUrl = await page.evaluate(probe);

  results.errors = errors;
  await browser.close();
  server.close();
  console.log(JSON.stringify(results));
})().catch((e) => { console.error(e); process.exit(1); });
