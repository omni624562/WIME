// 候選窗外觀共用資料與色彩工具（重構 A）。
//
// canonical 位置：python/cinbase/config/js/candidate_appearance.js
// 由兩個設定頁共用：
//   - cinbase（大易/酷倉等）config.htm：以 <script src="js/candidate_appearance.js">
//     透過既有 js/* 路由載入。
//   - chewing（新酷音）config_tool.html：以 <script src="candidate_appearance.js">
//     載入，由 chewing 的 config_tool.py 加一條路由指回本檔。
//
// 兩頁的 config.js 直接引用以下全域（候選窗主題色、樣式選項、色彩工具），
// 不再各自重複定義。之前這些資料重複在兩個 config.js 裡，每次調整配色/樣式
// 都得改兩遍且縮排/變數名不同易漏，故抽出集中於此。

// ---------------------------------------------------------------------------
// 色彩工具
// ---------------------------------------------------------------------------
function hexToRgb(color) {
    var value = (color || "").replace("#", "");
    if (value.length !== 6) {
        return null;
    }
    return {
        r: parseInt(value.substr(0, 2), 16),
        g: parseInt(value.substr(2, 2), 16),
        b: parseInt(value.substr(4, 2), 16)
    };
}

function blendHex(a, b, percentB) {
    var rgbA = hexToRgb(a);
    var rgbB = hexToRgb(b);
    if (!rgbA || !rgbB) {
        return b;
    }
    var percentA = 100 - percentB;
    var toHex = function (value) {
        var hex = Math.round(value).toString(16);
        return hex.length === 1 ? "0" + hex : hex;
    };
    return "#" +
        toHex((rgbA.r * percentA + rgbB.r * percentB) / 100) +
        toHex((rgbA.g * percentA + rgbB.g * percentB) / 100) +
        toHex((rgbA.b * percentA + rgbB.b * percentB) / 100);
}

function colorLuma(color) {
    var rgb = hexToRgb(color);
    if (!rgb) {
        return 0;
    }
    return Math.round((rgb.r * 299 + rgb.g * 587 + rgb.b * 114) / 1000);
}

function colorContrastHex(a, b) {
    return Math.abs(colorLuma(a) - colorLuma(b));
}

function readableTextOnHex(bg, preferred, alternate) {
    var dark = "#111827";
    var light = "#f8fafc";
    var result = preferred;
    var resultContrast = colorContrastHex(bg, result);
    var alternateContrast = colorContrastHex(bg, alternate);
    if (alternateContrast > resultContrast) {
        result = alternate;
        resultContrast = alternateContrast;
    }
    var darkContrast = colorContrastHex(bg, dark);
    var lightContrast = colorContrastHex(bg, light);
    if (resultContrast < 72 && darkContrast > resultContrast) {
        result = dark;
        resultContrast = darkContrast;
    }
    if (resultContrast < 72 && lightContrast > resultContrast) {
        result = light;
    }
    return result;
}

// ---------------------------------------------------------------------------
// 候選窗外觀資料
// ---------------------------------------------------------------------------
var candidateThemeNames = [
    "System",
    "Graphite",
    "Sepia Dim",
    "Plum",
    "Light",
    "Pure Black",
    "High Contrast"
];

var candidateThemePalette = {
    "Graphite": ["#12141a", "#444a57", "#292e38", "#f3f5fa", "#aeb5c4", "#8fb3ff", "#4169d7", "#6f92eb", "#edf3ff", "#9eb0d5"],
    "Sepia Dim": ["#28251f", "#5d564a", "#403a31", "#ebe2d3", "#b9ad9a", "#dfc58e", "#6d6547", "#958a63", "#f8efd9", "#c7b79e"],
    "Plum": ["#1d1721", "#604b66", "#382c3e", "#fbf4ff", "#c0adca", "#e0a7ff", "#7a55b8", "#aa83e6", "#fbf3ff", "#c5a9d1"],
    "Light": ["#f7f9fc", "#aeb8cb", "#dbe2ed", "#182235", "#657187", "#2f66dc", "#2f6eea", "#1d56c4", "#ffffff", "#44639a"],
    "Pure Black": ["#000000", "#3a3f46", "#22262b", "#e8eaed", "#9aa2ac", "#7fd1c0", "#1f6f63", "#3f9c8d", "#eafffb", "#a7b3ae"],
    "High Contrast": ["#0a0a0c", "#6b7280", "#33373d", "#ffffff", "#c9ced6", "#ffd75e", "#8a6d00", "#c7a83c", "#fff8dc", "#d6dae2"]
};

// 「System」跟隨 Windows 深淺色：預覽以瀏覽器的 prefers-color-scheme 對應
candidateThemePalette["System"] = (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches)
    ? candidateThemePalette["Graphite"]
    : candidateThemePalette["Light"];

var candidateKeyStyleOptions = {
    "word-first": "Word First"
};

var candidateMessageStyleOptions = {
    badge: "A Badge Alert",
    bar: "B Bar Notice",
    dot: "D Dot Signal"
};

var candidateHeaderStyleOptions = {
    accent: "Accent Name"
};

var candidateMessageBehaviorOptions = {
    fixed: "固定樣式",
    progressive: "打字中低調，確認後明顯"
};

var candidateKeyStyleClassNames = [
    "key-style-keycap",
    "key-style-quiet",
    "key-style-divider",
    "key-style-badge",
    "key-style-accent-dot",
    "key-style-rail",
    "key-style-monospace-slot",
    "key-style-word-first",
    "key-style-soft-capsule",
    "key-style-left-tag",
    "key-style-glow-key",
    "key-style-micro-tab",
    "key-style-word-anchor"
];
