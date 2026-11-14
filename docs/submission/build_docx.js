// Build the Word version of the submission document with thesis-style typography.
//
//   DOCX_MODULES=<node_modules with docx + image-size> node docs/submission/build_docx.js
//   uv run python docs/submission/post_docx.py      # native Word equations (OMML)
//
// Content lives in content.js; this file only knows layout: 宋体/黑体 with Times New Roman,
// 小四 body at 1.5 lines, three-line tables, numbered captions, header and page numbers.

const fs = require("fs");
const path = require("path");
// docx and image-size are build-time tools, not project dependencies: load them from DOCX_MODULES
const req = process.env.DOCX_MODULES ? require("module").createRequire(path.join(process.env.DOCX_MODULES, "_.js")) : require;
const sizeOf = req("image-size");
const {
  AlignmentType, BorderStyle, Document, Footer, Header, HeadingLevel, ImageRun, LineRuleType, Packer,
  PageBreak, PageNumber, NumberFormat, Paragraph, ShadingType, Table, TableCell, TableOfContents, TableRow,
  TabStopType, TextRun, VerticalAlign, WidthType,
} = req("docx");

const HERE = __dirname;
const OUT = path.join(HERE, "ConsentTrace-作品介绍文档.raw.docx"); // post_docx.py turns it into the final .docx

// ---------------------------------------------------------------- page and type
const CM = 567; // twips per cm
const MARGIN = { top: 2.5 * CM, bottom: 2.4 * CM, left: 3.0 * CM, right: 2.6 * CM };
const TEXT_W = Math.round(21 * CM - MARGIN.left - MARGIN.right); // 8732 twips ≈ 15.4 cm
const TEXT_PX = Math.round((TEXT_W / 1440) * 96);

const SONG = { ascii: "Times New Roman", hAnsi: "Times New Roman", cs: "Times New Roman", eastAsia: "宋体" };
const HEI = { ascii: "Times New Roman", hAnsi: "Times New Roman", cs: "Times New Roman", eastAsia: "黑体" };
const MONO = { ascii: "Consolas", hAnsi: "Consolas", cs: "Consolas", eastAsia: "宋体" };
const PT = (p) => Math.round(p * 2); // half-points
const SZ = { san: PT(16), si: PT(14), xiaosi: PT(12), wu: PT(10.5), xiaowu: PT(9), er: PT(22), xiaoer: PT(18), yi: PT(26) };
const LINE15 = { line: 360, lineRule: LineRuleType.AUTO };
const SINGLE = { line: 240, lineRule: LineRuleType.AUTO };

// ---------------------------------------------------------------- inline markup
// **bold**  `code`  {i:italic}  {sub:x}  {sup:x}  {b:bold}
function runs(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\{(i|sub|sup|b):[^}]*\})/g;
  let last = 0;
  let m;
  const push = (t, extra = {}) => {
    if (!t) return;
    out.push(new TextRun({ text: t, font: SONG, size: SZ.xiaosi, ...base, ...extra }));
  };
  while ((m = re.exec(text))) {
    push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) push(tok.slice(2, -2), { bold: true, font: base.font === MONO ? MONO : HEI });
    else if (tok.startsWith("`")) push(tok.slice(1, -1), { font: MONO, size: (base.size || SZ.xiaosi) - 2 });
    else {
      const kind = m[2];
      const body = tok.slice(kind.length + 2, -1);
      if (kind === "i") push(body, { italics: true });
      else if (kind === "b") push(body, { bold: true });
      else if (kind === "sub") push(body, { subScript: true });
      else push(body, { superScript: true });
    }
    last = m.index + tok.length;
  }
  push(text.slice(last));
  return out;
}

// ---------------------------------------------------------------- blocks
const H1 = (num, title) =>
  new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun({ text: `${num}　${title}` })] });
const H2 = (num, title) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun({ text: `${num}　${title}` })] });
const H3 = (num, title) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun({ text: `${num}　${title}` })] });

const P = (text, opts = {}) =>
  new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    spacing: { ...LINE15, before: 0, after: 0 },
    indent: opts.noIndent ? undefined : { firstLine: 480 },
    children: runs(text),
  });

// a run-in paragraph heading such as （1）……：
const PL = (lead, text) =>
  new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    spacing: { ...LINE15 },
    indent: { firstLine: 480 },
    children: [new TextRun({ text: lead, font: HEI, size: SZ.xiaosi }), ...runs(text)],
  });

function picture(file, widthCm, maxHeightCm = 13.5) {
  const full = path.join(HERE, file);
  const dim = sizeOf(full);
  let w = Math.min(widthCm ? (widthCm / 15.4) * TEXT_PX : TEXT_PX, TEXT_PX);
  let h = (w * dim.height) / dim.width;
  const maxH = (maxHeightCm / 15.4) * TEXT_PX;
  if (h > maxH) {
    w = (w * maxH) / h;
    h = maxH;
  }
  return new ImageRun({ type: dim.type === "jpg" ? "jpg" : "png", data: fs.readFileSync(full), transformation: { width: Math.round(w), height: Math.round(h) } });
}

const caption = (label, title) =>
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 60, after: 200, line: 300, lineRule: LineRuleType.AUTO },
    children: [new TextRun({ text: `${label}　`, font: HEI, size: SZ.wu, bold: false }), new TextRun({ text: title, font: HEI, size: SZ.wu })],
  });

const note = (text) =>
  new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    spacing: { before: 0, after: 200, line: 280, lineRule: LineRuleType.AUTO },
    indent: { left: 420, right: 420 },
    children: runs(text, { size: SZ.xiaowu }),
  });

// figure: image, caption below, optional note under the caption
function FIG(label, file, title, opts = {}) {
  const out = [
    new Paragraph({ alignment: AlignmentType.CENTER, keepNext: true, spacing: { before: 160, after: 0, ...SINGLE }, children: [picture(file, opts.width, opts.maxH)] }),
  ];
  const cap = caption(label, title);
  if (opts.note) {
    cap.options = cap.options || {};
    out.push(
      new Paragraph({
        alignment: AlignmentType.CENTER,
        keepNext: true,
        spacing: { before: 60, after: 40, line: 300, lineRule: LineRuleType.AUTO },
        children: [new TextRun({ text: `${label}　`, font: HEI, size: SZ.wu }), new TextRun({ text: title, font: HEI, size: SZ.wu })],
      }),
    );
    out.push(note(opts.note));
  } else out.push(cap);
  return out;
}

// two figures side by side, each with its own sub-caption, one shared caption
function FIG2(label, items, title, opts = {}) {
  const colW = Math.floor(TEXT_W / 2);
  const none = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
  const cells = items.map(
    ([file, sub]) =>
      new TableCell({
        width: { size: colW, type: WidthType.DXA },
        borders: { top: none, bottom: none, left: none, right: none },
        margins: { left: 60, right: 60 },
        children: [
          new Paragraph({ alignment: AlignmentType.CENTER, spacing: SINGLE, children: [picture(file, 7.4, opts.maxH || 9)] }),
          new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 40, after: 0, ...SINGLE }, children: [new TextRun({ text: sub, font: SONG, size: SZ.xiaowu })] }),
        ],
      }),
  );
  return [
    new Paragraph({ spacing: { before: 120, after: 0 }, keepNext: true, children: [] }),
    new Table({
      width: { size: colW * 2, type: WidthType.DXA },
      columnWidths: [colW, colW],
      alignment: AlignmentType.CENTER,
      borders: { top: none, bottom: none, left: none, right: none, insideHorizontal: none, insideVertical: none },
      rows: [new TableRow({ cantSplit: true, children: cells })],
    }),
    caption(label, title),
  ];
}

// three-line table; widths in cm, summing to ≤ 15.4
function TAB(label, title, widths, header, rows, opts = {}) {
  const total = widths.reduce((a, b) => a + b, 0);
  const tw = widths.map((w) => Math.round((w / total) * TEXT_W));
  const thick = { style: BorderStyle.SINGLE, size: 12, color: "000000" };
  const thin = { style: BorderStyle.SINGLE, size: 6, color: "000000" };
  const none = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
  const cellPara = (text, isHead, align) =>
    new Paragraph({
      alignment: align || (isHead ? AlignmentType.CENTER : AlignmentType.LEFT),
      spacing: { before: 20, after: 20, line: 280, lineRule: LineRuleType.AUTO },
      children: runs(text, { size: SZ.wu, font: isHead ? HEI : SONG }),
    });
  const mk = (cells, i, isHead, last) =>
    new TableRow({
      tableHeader: isHead,
      cantSplit: true,
      children: cells.map(
        (c, j) =>
          new TableCell({
            width: { size: tw[j], type: WidthType.DXA },
            verticalAlign: VerticalAlign.CENTER,
            margins: { top: 30, bottom: 30, left: 80, right: 80 },
            shading: opts.highlight === i && !isHead ? { type: ShadingType.CLEAR, fill: "EEF3FA", color: "auto" } : undefined,
            borders: { left: none, right: none, top: isHead ? thick : none, bottom: isHead ? thin : last ? thick : none },
            children: String(c).split("\n").map((line) => cellPara(line, isHead, opts.align && opts.align[j])),
          }),
      ),
    });
  return [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      keepNext: true,
      spacing: { before: 200, after: 60, line: 300, lineRule: LineRuleType.AUTO },
      children: [new TextRun({ text: `${label}　`, font: HEI, size: SZ.wu }), new TextRun({ text: title, font: HEI, size: SZ.wu })],
    }),
    new Table({
      width: { size: TEXT_W, type: WidthType.DXA },
      columnWidths: tw,
      alignment: AlignmentType.CENTER,
      borders: { top: none, bottom: none, left: none, right: none, insideHorizontal: none, insideVertical: none },
      rows: [mk(header, -1, true, false), ...rows.map((r, i) => mk(r, i, false, i === rows.length - 1))],
    }),
    new Paragraph({ spacing: { before: 0, after: 120 }, children: [] }),
  ];
}

// equation placeholder; post_docx.py swaps the paragraph for a native Word equation
const EQ = (id) => new Paragraph({ children: [new TextRun({ text: `⟦EQ:${id}⟧` })] });

function CODE(label, title, lines) {
  const bd = { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF", space: 4 };
  const out = lines.map(
    (line, i) =>
      new Paragraph({
        keepNext: i < lines.length - 1,
        keepLines: true,
        spacing: { before: 0, after: 0, line: 250, lineRule: LineRuleType.AUTO },
        indent: { left: 200, right: 200 },
        shading: { type: ShadingType.CLEAR, fill: "F5F5F3", color: "auto" },
        border: { top: i === 0 ? bd : undefined, bottom: i === lines.length - 1 ? bd : undefined, left: bd, right: bd },
        children: [new TextRun({ text: line.length ? line : " ", font: MONO, size: PT(8.5) })],
      }),
  );
  out.unshift(new Paragraph({ spacing: { before: 120, after: 0 }, keepNext: true, children: [] }));
  out.push(caption(label, title));
  return out;
}

function BOX(title, text) {
  const bd = { style: BorderStyle.SINGLE, size: 6, color: "7F7F7F", space: 6 };
  const left = { style: BorderStyle.SINGLE, size: 24, color: "404040", space: 6 };
  return [
    new Paragraph({
      keepNext: true,
      spacing: { before: 160, after: 0, ...LINE15 },
      indent: { left: 240, right: 240 },
      shading: { type: ShadingType.CLEAR, fill: "F3F3F1", color: "auto" },
      border: { top: bd, left, right: bd },
      children: [new TextRun({ text: title, font: HEI, size: SZ.wu })],
    }),
    new Paragraph({
      alignment: AlignmentType.JUSTIFIED,
      spacing: { before: 0, after: 200, line: 320, lineRule: LineRuleType.AUTO },
      indent: { left: 240, right: 240 },
      shading: { type: ShadingType.CLEAR, fill: "F3F3F1", color: "auto" },
      border: { bottom: bd, left, right: bd },
      children: runs(text, { size: SZ.wu }),
    }),
  ];
}

const BLANK = (n = 1) => Array.from({ length: n }, () => new Paragraph({ spacing: LINE15, children: [] }));

// ---------------------------------------------------------------- document
const content = require("./content.js")({ H1, H2, H3, P, PL, FIG, FIG2, TAB, EQ, CODE, BOX, BLANK, runs, SONG, HEI, SZ, TextRun, Paragraph, AlignmentType, BorderStyle, ShadingType, LINE15 });

const headerPara = () =>
  new Header({
    children: [
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 0 },
        border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "000000", space: 2 } },
        children: [new TextRun({ text: "ConsentTrace：面向多轮授权变更与工具注入的 AI 智能体授权链路测试平台 · 作品介绍文档", font: SONG, size: SZ.xiaowu })],
      }),
    ],
  });
const footerPara = () =>
  new Footer({
    children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: [PageNumber.CURRENT], font: SONG, size: SZ.xiaowu })] })],
  });

const page = (start, fmt) => ({
  page: { size: { width: 21 * CM, height: 29.7 * CM }, margin: { ...MARGIN, header: 1.5 * CM, footer: 1.5 * CM }, pageNumbers: { start, formatType: fmt } },
});

const doc = new Document({
  creator: "ConsentTrace",
  title: "ConsentTrace 作品介绍文档",
  features: { updateFields: true }, // Word asks once on open and fills the table of contents
  styles: {
    default: {
      document: { run: { font: SONG, size: SZ.xiaosi }, paragraph: { spacing: LINE15 } },
      heading1: {
        run: { font: HEI, size: SZ.san, bold: false, color: "000000" },
        paragraph: { alignment: AlignmentType.CENTER, spacing: { before: 240, after: 360, ...LINE15 }, keepNext: true, outlineLevel: 0 },
      },
      heading2: {
        run: { font: HEI, size: SZ.si, bold: false, color: "000000" },
        paragraph: { spacing: { before: 240, after: 120, ...LINE15 }, keepNext: true, outlineLevel: 1 },
      },
      heading3: {
        run: { font: HEI, size: SZ.xiaosi, bold: false, color: "000000" },
        paragraph: { spacing: { before: 160, after: 80, ...LINE15 }, keepNext: true, outlineLevel: 2 },
      },
    },
  },
  sections: [
    { properties: { ...page(1, NumberFormat.DECIMAL), titlePage: true }, children: content.cover },
    {
      properties: page(1, NumberFormat.UPPER_ROMAN),
      headers: { default: headerPara() },
      footers: { default: footerPara() },
      children: [
        new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 240, after: 360 }, children: [new TextRun({ text: "目　　录", font: HEI, size: SZ.san })] }),
        new TableOfContents("目录", { hyperlink: true, headingStyleRange: "1-3" }),
      ],
    },
    { properties: page(1, NumberFormat.DECIMAL), headers: { default: headerPara() }, footers: { default: footerPara() }, children: content.body },
  ],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log(OUT, buf.length);
});
