
var defaultcinCount = {
    "big5F": 0,
    "big5LF": 0,
    "big5Other": 0,
    "big5S": 0,
    "bopomofo": 0,
    "cjk": 0,
    "cjkCI": 0,
    "cjkCIS": 0,
    "cjkExtA": 0,
    "cjkExtB": 0,
    "cjkExtC": 0,
    "cjkExtD": 0,
    "cjkExtE": 0,
    "cjkExtF": 0,
    "cjkOther": 0,
    "phrases": 0,
    "privateuse": 0,
    "totalchardefs": 0
}

var selRCins = [
    "酷倉",
    "倉頡",
    "倉頡(大字集)",
    "雅虎倉頡",
    "中標倉頡",
    "泰瑞倉頡",
    "亂倉打鳥",
    "倉頡五代",
    "自由大新倉頡",
    "快倉六代",
    "倉捷",
    "泰瑞注音",
    "中標注音",
    "傳統注音",
    "泰瑞行列30",
    "行列30",
    "行列30大字集",
    "行列40",
    "泰瑞大易四碼",
    "大易四碼",
    "大易三碼",
    "輕鬆",
    "輕鬆小詞庫",
    "輕鬆中詞庫",
    "輕鬆大詞庫",
    "泰瑞拼音",
    "正體拼音",
    "羅馬拼音",
    "正體簡易",
    "速成",
    "簡易五代",
    "嘸蝦米"
];

var selHCins = [
    "泰瑞注音",
    "中標注音",
    "傳統注音"
];

var debugMode = false;
var checjConfig = {};
var cinCount = {};
var rcinAvailable = null; // 有安裝碼表檔的反查碼表索引（設定工具提供；沒有時全部列出）
var configLoaded = false;
var configLoadFailed = false;

// 設定工具伺服器回應失敗時的說明。403 = 工作階段已失效（在別處重新開了設定、
// 或伺服器已重啟換了 token）；0 = 連不到伺服器（已結束）。
function serverErrorMessage(xhr, action) {
    var status = xhr ? xhr.status : 0;
    if (status === 403) {
        return action + "失敗：設定工具的工作階段已失效。<br>請關閉此頁，再從輸入法的「設定」重新開啟。";
    }
    if (!status) {
        return action + "失敗：無法連線到設定工具（可能已關閉）。<br>請關閉此頁，再從輸入法的「設定」重新開啟。";
    }
    return action + "失敗（HTTP " + status + "）。<br>請關閉此頁後重新開啟設定再試一次。";
}

// 載入失敗時頁面欄位全是空的，放一條固定橫幅說明原因，而不是留一頁空白。
function showConfigLoadError(xhr) {
    $(function() {
        if (document.getElementById("configLoadError")) {
            return;
        }
        $("<div>", { id: "configLoadError", role: "alert" })
            .css({ position: "fixed", top: 0, left: 0, right: 0, zIndex: 10000, padding: "12px 16px",
                   background: "#b42318", color: "#fff", fontWeight: "bold", textAlign: "center" })
            .html(serverErrorMessage(xhr, "載入設定"))
            .prependTo("body");
    });
}

// 儲存失敗一定要讓使用者知道，否則會以為已經存好了。
function showConfigSaveError(xhr) {
    var message;
    if (xhr && xhr.status === 500) {
        // 設定工具寫不進設定檔（例如 config.json 正被其他程式開著）。工作階段還有效，
        // 關掉頁面反而會丟掉這次的變更，請使用者稍後再按一次即可。
        message = "儲存設定失敗：設定檔無法寫入（可能正被其他程式開著）。<br>" +
            "頁面上的變更還在，請稍後再按一次「套用設定」。";
    } else {
        message = serverErrorMessage(xhr, "儲存設定") + "<br>這次的變更尚未儲存。";
    }
    if ($.jAlert) {
        $.jAlert({
            'title': '儲存失敗',
            'content': message,
            'theme': 'dark_red',
            'size': 'md',
            'blurBackground': true,
            'closeOnClick': true,
            'btns': {'text': '關閉', 'theme': 'blue'}
        });
    } else {
        alert(message.replace(/<br>/g, "\n"));
    }
}
var CONFIG_URL = '/config';
var VERSION_URL = '/version.txt';
var KEEP_ALIVE_URL = '/keep_alive';
var hasInnerText = (document.getElementsByTagName("body")[0].innerText !== undefined) ? true : false;

var symbolsChanged = false;
var swkbChanged = false;
var fsymbolsChanged = false;
var phraseChanged = false;
var excludePhraseChanged = false;
var flangsChanged = false;
var extendtableChanged = false;

var symbolsData = "";
var swkbData = "";
var fsymbolsData = "";
var phraseData = "";
var excludePhraseData = "";
var flangsData = "";
var extendtableData = "";

var isIE = (function() {
    var browser = {};
    return function(ver,c) {
        var key = ver ?  ( c ? "is"+c+"IE"+ver : "isIE"+ver ) : "isIE";
        var v = browser[key];
        if (typeof(v) != "undefined") {
            return v;
        }
        if (!ver) {
            v = (navigator.userAgent.indexOf('MSIE') !== -1 || navigator.appVersion.indexOf('Trident/') > 0);
        } else {
            var match = navigator.userAgent.match(/(?:MSIE |Trident\/.*; rv:|Edge\/)(\d+)/);
                if (match) {
                    var v1 = parseInt(match[1]);
                    v = c ?  ( c == 'lt' ?  v1 < ver  :  ( c == 'gt' ?  v1 >  ver : undefined ) ) : v1 == ver;
                } else if (ver <= 9) {
                    var b = document.createElement('b')
                    var s = '<!--[if '+(c ? c : '')+' IE '  + ver + ']><i></i><![endif]-->';
                    b.innerHTML = s;
                    v =  b.getElementsByTagName('i').length == 1;
                } else {
                    v = undefined;
                }
        }
        browser[key] = v;
        return v;
    };
}());

var isOldIE = (isIE() && isIE(9, 'lt'))

if (!isOldIE) {
    includeScriptFile("js/jAlert/jAlert.min.js")
} else {
    includeScriptFile("js/jAlert/jAlert-ie8.min.js")
}

if (!Date.now) {
    Date.now = function() {
        return new Date().valueOf();
    }
}

function loadConfig() {
    $.get(CONFIG_URL, function(data, status) {
        checjConfig = data.config;
        applyCandidateDefaults();
        cinCount = data.cincount;
        rcinAvailable = data.rcinAvailable || null;
        symbolsData = data.symbols;
        swkbData = data.swkb;
        fsymbolsData = data.fsymbols;
        phraseData = data.phrase;
        excludePhraseData = data.excludePhrase || "";
        flangsData = data.flangs;
        extendtableData = data.extendtable;
        configLoaded = true;
    }, "json").fail(function(xhr) {
        configLoadFailed = true;
        showConfigLoadError(xhr);
    });
}
loadConfig();

function applyCandidateDefaults() {
    var currentIme = typeof imeFolderName !== "undefined" ? imeFolderName : "";
    if (typeof checjConfig.autoCommitSingleCandidate === "undefined") {
        checjConfig.autoCommitSingleCandidate = false;
    }
    if (typeof checjConfig.intelligentSelect === "undefined") {
        checjConfig.intelligentSelect = true;
    }
    if (typeof checjConfig.intelligentSelectRecent === "undefined") {
        checjConfig.intelligentSelectRecent = true;
    }
    if (typeof checjConfig.intelligentSelectContext === "undefined") {
        checjConfig.intelligentSelectContext = true;
    }
    // 舊的設定檔與後端都沒有這個鍵時，維持以前一律以 Shift+空白鍵切換全半形的行為
    if (typeof checjConfig.enableShiftSpace === "undefined") {
        checjConfig.enableShiftSpace = true;
    }
    // 選字符樣式只提供 Word First，一律固定為 word-first
    checjConfig.candidateKeyStyle = "word-first";
    if (typeof checjConfig.candidateMessageStyle === "undefined") {
        checjConfig.candidateMessageStyle = "badge";
    }
    if (typeof checjConfig.candidateMessageBehavior === "undefined") {
        checjConfig.candidateMessageBehavior = "progressive";
    }
    // candidateKeyStyle 已固定為 word-first，無需驗證清單
    var validCandidateMessageStyles = {
        badge: true,
        bar: true,
        dot: true
    };
    if (!validCandidateMessageStyles[checjConfig.candidateMessageStyle]) {
        checjConfig.candidateMessageStyle = "badge";
    }
    var validCandidateMessageBehaviors = {
        fixed: true,
        progressive: true
    };
    if (!validCandidateMessageBehaviors[checjConfig.candidateMessageBehavior]) {
        checjConfig.candidateMessageBehavior = "progressive";
    }
    // 輸入法名稱標籤樣式只提供 Accent Name，一律固定為 accent
    checjConfig.candidateHeaderStyle = "accent";
    // 已移除的設定（舊版候選窗開關、提示訊息顯示時間、隱藏提示訊息），存檔時不再寫回
    ["candidateModernStyle", "messageDurationTime", "hidePromptMessages"].forEach(function(key) {
        delete checjConfig[key];
    });
    var modernDefaultIme = ["chedayi", "checj", "cheliu"].indexOf(currentIme) >= 0;
    if (!modernDefaultIme) {
        return;
    }
    if (typeof checjConfig.candidateStableWidth === "undefined") {
        checjConfig.candidateStableWidth = true;
    }
    if (typeof checjConfig.candidateMinWidth === "undefined" || checjConfig.candidateMinWidth < 160) {
        checjConfig.candidateMinWidth = 286;
    }
    if (typeof checjConfig.candidateWrapToMaxWidth === "undefined") {
        checjConfig.candidateWrapToMaxWidth = true;
    }
    // 300 放不下一列 6 個候選字（100% 縮放要 306px），會換成 5+1 兩列
    if (typeof checjConfig.candidateMaxWidth === "undefined" || checjConfig.candidateMaxWidth < 220) {
        checjConfig.candidateMaxWidth = 320;
    }
    // 別名（大小寫/空白不同、舊分支的命名）對回正式名稱；被移除的主題退回 System
    checjConfig.candidateTheme = canonicalCandidateThemeName(checjConfig.candidateTheme);
    if (typeof checjConfig.candidatePerRow === "undefined") {
        checjConfig.candidatePerRow = 6;
    }
    if (typeof checjConfig.candidateEdgeAvoidance === "undefined") {
        checjConfig.candidateEdgeAvoidance = true;
    }
    if (typeof checjConfig.candidatePositionMode === "undefined") {
        checjConfig.candidatePositionMode = 0;
    }
    if (typeof checjConfig.candidateOpacity === "undefined" ||
        checjConfig.candidateOpacity < 30 || checjConfig.candidateOpacity > 100) {
        checjConfig.candidateOpacity = 100;
    }
}

// 候選窗外觀資料（themeNames / palette / 各樣式 options / classNames）
// 已抽至 js/candidate_appearance.js（重構 A），於此檔前先行載入。

function getCandidatePreviewSample() {
    var previewName = checjConfig.imeDisplayName || "大易";
    var root = "月";
    var candidates = ["明", "朋", "服", "朗", "朝", "朔", "期", "望", "有", "肚"];
    var selKeys = "1234567890";

    if (imeFolderName == "chedayi") {
        previewName = checjConfig.imeDisplayName || "大易";
        root = "魚";
        candidates = ["刀", "川", "夕", "角", "魚", "互", "句", "象", "魯", "鮮"];
        selKeys = "␣'[]-\\";
    }
    else if (imeFolderName == "checj") {
        previewName = checjConfig.imeDisplayName || "酷倉";
        root = "一日";
        candidates = ["是", "題", "暫", "量", "更", "旦", "曹", "晉", "晝", "書"];
    }
    else if (imeFolderName == "cheliu") {
        previewName = checjConfig.imeDisplayName || "蝦米";
        root = "魚";
        candidates = ["魯", "鮮", "鯉", "鯨", "鱗", "鰭", "鯛", "鰻", "鯨", "鱸"];
    }

    return {
        name: previewName,
        root: root,
        candidates: candidates,
        selKeys: selKeys
    };
}

// 色彩工具（hexToRgb / blendHex / colorLuma / colorContrastHex /
// readableTextOnHex）已抽至 js/candidate_appearance.js（重構 A）。

function applyCandidatePreviewTheme(preview, theme) {
    var selectedBg = blendHex(theme[0], theme[6], 28);
    var selectedFg = readableTextOnHex(selectedBg, theme[8], theme[3]);
    var selectedBorder = colorContrastHex(selectedBg, theme[7]) >= 38 ? blendHex(theme[7], selectedBg, 28) : blendHex(selectedFg, selectedBg, 40);
    preview.css({
        "background-color": theme[0],
        "border-color": theme[1],
        "border-radius": "6px",
        "color": theme[3]
    });
    preview.find(".candidate-preview-header").css("border-bottom-color", theme[2]);
    preview.find(".candidate-preview-name, .candidate-preview-page").css("color", theme[4]);
    preview.find(".candidate-preview-root").css("color", theme[5]);
    preview.find(".candidate-preview-key").css("color", theme[9]);
    preview.find(".candidate-preview-word").css("color", theme[3]);
    preview.find(".candidate-preview-item.active").css({
        "background-color": selectedBg,
        "border-color": selectedBorder,
        "border-radius": "6px",
        "color": selectedFg
    });
    preview.find(".candidate-preview-item.active .candidate-preview-key, .candidate-preview-item.active .candidate-preview-word").css("color", selectedFg);
}

function applyCandidatePreviewKeyStyle(preview, keyStyle) {
    keyStyle = keyStyle || $("#candidateKeyStyle").val() || checjConfig.candidateKeyStyle || "word-first";
    preview
        .removeClass(candidateKeyStyleClassNames.join(" "))
        .addClass("key-style-" + keyStyle);
}

function fillCandidatePreviewItems(preview, sample) {
    var count = parseInt($("#candidatePerRow").val(), 10) || 4;
    count = Math.max(1, Math.min(count, 10));
    var selKeys = sample.selKeys || "1234567890";
    var body = preview.find(".candidate-preview-body");
    body.empty();

    for (var i = 0; i < count; ++i) {
        var item = $("<span>").addClass("candidate-preview-item");
        if (i == 0) {
            item.addClass("active");
        }
        item.append($("<span>").addClass("candidate-preview-key").text(selKeys.charAt(i % selKeys.length)));
        item.append($("<span>").addClass("candidate-preview-word").text(sample.candidates[i % sample.candidates.length]));
        body.append(item);
    }
}

function candidatePreviewFontSize() {
    var fontSize = parseInt($("#fontSize").val(), 10) || 12;
    return Math.max(6, Math.min(fontSize, 48));
}

function createCandidatePreview(sample, keyStyle, headerStyle) {
    var preview = $("<div>").addClass("candidate-preview");
    headerStyle = headerStyle || $("#candidateHeaderStyle").val() || "accent";
    preview.addClass("header-style-" + headerStyle);
    var header = $("<div>").addClass("candidate-preview-header");
    header.append($("<span>").addClass("candidate-preview-name").text(sample.name));
    header.append($("<span>").addClass("candidate-preview-root").text(sample.root));
    header.append($("<span>").addClass("candidate-preview-page").text("1/1"));
    preview.append(header);
    preview.append($("<div>").addClass("candidate-preview-body"));
    fillCandidatePreviewItems(preview, sample);
    applyCandidatePreviewKeyStyle(preview, keyStyle);
    return preview;
}

function applyCandidatePreviewMessageTheme(preview, theme) {
    var accent = theme[7];
    var messageBg = colorLuma(theme[0]) > 165 ? blendHex(theme[0], accent, 8) : blendHex(theme[0], accent, 13);
    var messageText = colorLuma(theme[0]) > 165 ? "#7a430d" : blendHex(theme[3], accent, 38);
    var badgeText = colorLuma(accent) > 150 ? "#1b1c20" : "#ffffff";
    preview.css({
        "--candidate-message-accent": accent,
        "--candidate-message-bg": messageBg,
        "--candidate-message-text": messageText,
        "--candidate-message-badge-text": badgeText
    });
}

function createCandidateMessagePreview(sample, messageStyle) {
    var preview = $("<div>").addClass("candidate-preview candidate-message-preview message-style-" + messageStyle);
    var header = $("<div>").addClass("candidate-preview-header");
    header.append($("<span>").addClass("candidate-preview-name").text(sample.name));
    header.append($("<span>").addClass("candidate-preview-root").text(sample.root + sample.root + sample.root));
    preview.append(header);

    var body = $("<div>").addClass("candidate-preview-body candidate-preview-message-body");
    var row = $("<div>").addClass("candidate-preview-message-row");
    if (messageStyle == "badge") {
        row.append($("<span>").addClass("candidate-preview-message-badge").text("!"));
    }
    else if (messageStyle == "dot") {
        row.append($("<span>").addClass("candidate-preview-message-dot"));
    }
    row.append($("<span>").addClass("candidate-preview-message-text").text("查無組字"));
    body.append(row);
    preview.append(body);
    return preview;
}

function createCandidateMessageBehaviorPreview(sample, behavior, selectedStyle) {
    var wrap = $("<div>").addClass("candidate-behavior-preview");
    var typingStyle = behavior == "progressive" ? "dot" : selectedStyle;
    var confirmedStyle = selectedStyle;

    wrap.append($("<div>").addClass("candidate-behavior-label").text(behavior == "progressive" ? "打字中：低調" : "打字中：固定樣式"));
    wrap.append(createCandidateMessagePreview(sample, typingStyle));
    wrap.append($("<div>").addClass("candidate-behavior-label").text(behavior == "progressive" ? "確認後：選用樣式" : "確認後：固定樣式"));
    wrap.append(createCandidateMessagePreview(sample, confirmedStyle));
    return wrap;
}

function renderCandidateThemeGallery() {
    var grid = $("#candidateThemeGrid");
    if (!grid.length) {
        return;
    }

    var sample = getCandidatePreviewSample();
    grid.empty();
    for (var i = 0; i < candidateThemeNames.length; ++i) {
        var themeName = candidateThemeNames[i];
        var card = $("<button>").attr("type", "button").addClass("candidate-theme-card").data("theme", themeName);
        var header = $("<div>").addClass("candidate-theme-card-header");
        header.append($("<span>").addClass("candidate-theme-card-name").text(themeName));
        header.append($("<span>").addClass("candidate-theme-card-state"));
        card.append(header);
        card.append(createCandidatePreview(sample));
        grid.append(card);
    }
}

function renderCandidateKeyStyleGallery() {
    var grid = $("#candidateKeyStyleGrid");
    if (!grid.length) {
        return;
    }

    var sample = getCandidatePreviewSample();
    grid.empty();
    $.each(candidateKeyStyleOptions, function(styleValue, styleName) {
        var card = $("<button>").attr("type", "button").addClass("candidate-style-card").data("style", styleValue);
        var header = $("<div>").addClass("candidate-style-card-header");
        header.append($("<span>").addClass("candidate-style-card-name").text(styleName));
        header.append($("<span>").addClass("candidate-style-card-state"));
        card.append(header);
        card.append(createCandidatePreview(sample, styleValue));
        grid.append(card);
    });
}

function renderCandidateHeaderStyleGallery() {
    var grid = $("#candidateHeaderStyleGrid");
    if (!grid.length) {
        return;
    }

    var sample = getCandidatePreviewSample();
    var keyStyle = $("#candidateKeyStyle").val() || "word-first";
    grid.empty();
    $.each(candidateHeaderStyleOptions, function(styleValue, styleName) {
        var card = $("<button>").attr("type", "button").addClass("candidate-style-card candidate-header-style-card").data("style", styleValue);
        var header = $("<div>").addClass("candidate-style-card-header");
        header.append($("<span>").addClass("candidate-style-card-name").text(styleName));
        header.append($("<span>").addClass("candidate-style-card-state"));
        card.append(header);
        card.append(createCandidatePreview(sample, keyStyle, styleValue));
        grid.append(card);
    });
}

function renderCandidateMessageStyleGallery() {
    var grid = $("#candidateMessageStyleGrid");
    if (!grid.length) {
        return;
    }

    var sample = getCandidatePreviewSample();
    grid.empty();
    $.each(candidateMessageStyleOptions, function(styleValue, styleName) {
        var card = $("<button>").attr("type", "button").addClass("candidate-style-card candidate-message-style-card").data("style", styleValue);
        var header = $("<div>").addClass("candidate-style-card-header");
        header.append($("<span>").addClass("candidate-style-card-name").text(styleName));
        header.append($("<span>").addClass("candidate-style-card-state"));
        card.append(header);
        card.append(createCandidateMessagePreview(sample, styleValue));
        grid.append(card);
    });
}

function renderCandidateMessageBehaviorGallery() {
    var grid = $("#candidateMessageBehaviorGrid");
    if (!grid.length) {
        return;
    }

    var sample = getCandidatePreviewSample();
    var selectedStyle = $("#candidateMessageStyle").val() || "badge";
    grid.empty();
    $.each(candidateMessageBehaviorOptions, function(behaviorValue, behaviorName) {
        var card = $("<button>").attr("type", "button").addClass("candidate-style-card candidate-message-behavior-card").data("behavior", behaviorValue);
        var header = $("<div>").addClass("candidate-style-card-header");
        header.append($("<span>").addClass("candidate-style-card-name").text(behaviorName));
        header.append($("<span>").addClass("candidate-style-card-state"));
        card.append(header);
        card.append(createCandidateMessageBehaviorPreview(sample, behaviorValue, selectedStyle));
        grid.append(card);
    });
}

function updateCandidateThemeGallery() {
    var grid = $("#candidateThemeGrid");
    if (!grid.length) {
        return;
    }

    var selectedTheme = $("#candidateTheme").val() || "System";
    var stableWidth = $("#candidateStableWidth").prop("checked");
    var wrapToMaxWidth = $("#candidateWrapToMaxWidth").prop("checked");
    var selectedStyle = $("#candidateKeyStyle").val() || "word-first";
    var sample = getCandidatePreviewSample();
    $("#candidateMinWidth").prop("disabled", !stableWidth);
    $("#candidateMaxWidth").prop("disabled", !wrapToMaxWidth);
    $("#candidateThemeCurrent").text(selectedTheme);

    grid.find(".candidate-theme-card").each(function() {
        var card = $(this);
        var themeName = card.data("theme");
        var selected = themeName == selectedTheme;
        var preview = card.find(".candidate-preview");
        card.toggleClass("selected", selected);
        preview.toggleClass("wrap", wrapToMaxWidth);
        preview.css("font-size", candidatePreviewFontSize() + "pt");
        card.find(".candidate-theme-card-state").text(selected ? "已選" : "");
        preview.find(".candidate-preview-name").text(sample.name);
        preview.find(".candidate-preview-root").text(sample.root);
        fillCandidatePreviewItems(preview, sample);
        applyCandidatePreviewKeyStyle(preview, selectedStyle);
        applyCandidatePreviewTheme(preview, candidateThemePalette[themeName] || candidateThemePalette["Graphite"]);
    });
}

function updateCandidateKeyStyleGallery() {
    var grid = $("#candidateKeyStyleGrid");
    if (!grid.length) {
        return;
    }

    var selectedStyle = $("#candidateKeyStyle").val() || "word-first";
    var selectedTheme = $("#candidateTheme").val() || "System";
    var wrapToMaxWidth = $("#candidateWrapToMaxWidth").prop("checked");
    var sample = getCandidatePreviewSample();
    $("#candidateKeyStyleCurrent").text(candidateKeyStyleOptions[selectedStyle] || "");

    grid.find(".candidate-style-card").each(function() {
        var card = $(this);
        var styleValue = card.data("style");
        var selected = styleValue == selectedStyle;
        var preview = card.find(".candidate-preview");
        card.toggleClass("selected", selected);
        preview.toggleClass("wrap", wrapToMaxWidth);
        preview.css("font-size", candidatePreviewFontSize() + "pt");
        card.find(".candidate-style-card-state").text(selected ? "已選" : "");
        preview.find(".candidate-preview-name").text(sample.name);
        preview.find(".candidate-preview-root").text(sample.root);
        fillCandidatePreviewItems(preview, sample);
        applyCandidatePreviewKeyStyle(preview, styleValue);
        applyCandidatePreviewTheme(preview, candidateThemePalette[selectedTheme] || candidateThemePalette["Graphite"]);
    });
}

function updateCandidateMessageStyleGallery() {
    var grid = $("#candidateMessageStyleGrid");
    if (!grid.length) {
        return;
    }

    var selectedStyle = $("#candidateMessageStyle").val() || "badge";
    var selectedTheme = $("#candidateTheme").val() || "System";
    var sample = getCandidatePreviewSample();
    $("#candidateMessageStyleCurrent").text(candidateMessageStyleOptions[selectedStyle] || "");

    grid.find(".candidate-message-style-card").each(function() {
        var card = $(this);
        var styleValue = card.data("style");
        var selected = styleValue == selectedStyle;
        var preview = card.find(".candidate-preview");
        card.toggleClass("selected", selected);
        preview.css("font-size", candidatePreviewFontSize() + "pt");
        card.find(".candidate-style-card-state").text(selected ? "已選" : "");
        preview.find(".candidate-preview-name").text(sample.name);
        preview.find(".candidate-preview-root").text(sample.root + sample.root + sample.root);
        applyCandidatePreviewTheme(preview, candidateThemePalette[selectedTheme] || candidateThemePalette["Graphite"]);
        applyCandidatePreviewMessageTheme(preview, candidateThemePalette[selectedTheme] || candidateThemePalette["Graphite"]);
    });
}

function updateCandidateMessageBehaviorGallery() {
    var grid = $("#candidateMessageBehaviorGrid");
    if (!grid.length) {
        return;
    }

    var selectedBehavior = $("#candidateMessageBehavior").val() || "progressive";
    var selectedStyle = $("#candidateMessageStyle").val() || "badge";
    var selectedTheme = $("#candidateTheme").val() || "System";
    var sample = getCandidatePreviewSample();
    $("#candidateMessageBehaviorCurrent").text(candidateMessageBehaviorOptions[selectedBehavior] || "");

    grid.find(".candidate-message-behavior-card").each(function() {
        var card = $(this);
        var behaviorValue = card.data("behavior");
        var selected = behaviorValue == selectedBehavior;
        card.toggleClass("selected", selected);
        card.find(".candidate-style-card-state").text(selected ? "已選" : "");
        card.find(".candidate-behavior-preview").remove();
        card.append(createCandidateMessageBehaviorPreview(sample, behaviorValue, selectedStyle));
        card.find(".candidate-preview").each(function() {
            var preview = $(this);
            preview.css("font-size", candidatePreviewFontSize() + "pt");
            applyCandidatePreviewTheme(preview, candidateThemePalette[selectedTheme] || candidateThemePalette["Graphite"]);
            applyCandidatePreviewMessageTheme(preview, candidateThemePalette[selectedTheme] || candidateThemePalette["Graphite"]);
        });
    });
}

function updateCandidateHeaderStyleGallery() {
    var grid = $("#candidateHeaderStyleGrid");
    if (!grid.length) {
        return;
    }

    var selectedStyle = $("#candidateHeaderStyle").val() || "accent";
    var selectedTheme = $("#candidateTheme").val() || "System";
    var sample = getCandidatePreviewSample();
    $("#candidateHeaderStyleCurrent").text(candidateHeaderStyleOptions[selectedStyle] || "");

    grid.find(".candidate-header-style-card").each(function() {
        var card = $(this);
        var styleValue = card.data("style");
        var selected = styleValue == selectedStyle;
        var preview = card.find(".candidate-preview");
        card.toggleClass("selected", selected);
        preview.css("font-size", candidatePreviewFontSize() + "pt");
        card.find(".candidate-style-card-state").text(selected ? "已選" : "");
        preview.find(".candidate-preview-name").text(sample.name);
        preview.find(".candidate-preview-root").text(sample.root);
        applyCandidatePreviewTheme(preview, candidateThemePalette[selectedTheme] || candidateThemePalette["Graphite"]);
    });
}

function updateCandidateAppearanceGalleries() {
    updateCandidateThemeGallery();
    updateCandidateKeyStyleGallery();
    updateCandidateHeaderStyleGallery();
    updateCandidateMessageStyleGallery();
    updateCandidateMessageBehaviorGallery();
}

function saveConfig(callbackFunc) {
    // 候選窗最大寬度 300 是舊的預設值，後端只把沒有這個標記的設定檔裡的 300 換成
    // 新預設值。從設定頁存過的寬度都是使用者看過的值，之後刻意選的 300 要保留
    checjConfig.candidateMaxWidthMigrated = true;

    var data = {
        "config": checjConfig
    }

    // 只檢查這次改過、要一起送出的文字資料。沒改的不會送出，檔案裡原有的內容
    // （例如在記事本裡改過）不該擋住主題、字型等其他設定的儲存
    var textData = [
        { changed: symbolsChanged, elementId: "#symbols", type: "2", desc: "特殊符號", key: "symbols" },
        { changed: swkbChanged, elementId: "#ez_symbols", type: "1", desc: "簡易符號", key: "swkb" },
        { changed: fsymbolsChanged, elementId: "#fs_symbols", type: "2", desc: "全形標點符號", key: "fsymbols" },
        { changed: phraseChanged, elementId: "#phrase", type: "2", desc: "聯想字詞", key: "phrase" },
        { changed: excludePhraseChanged, elementId: "#excludePhrase", type: "2", desc: "排除聯想字詞", key: "excludePhrase" },
        { changed: flangsChanged, elementId: "#flangs", type: "2", desc: "外語文字", key: "flangs" },
        { changed: extendtableChanged, elementId: "#extendtable", type: "3", desc: "擴展碼表", key: "extendtable" }
    ];
    for (var i = 0; i < textData.length; i++) {
        var item = textData[i];
        if (!item.changed) {
            continue;
        }
        var value = $(item.elementId).val();
        if (!checkDataFormat(value, item.type, item.elementId, item.desc)) {
            return false;
        }
        data[item.key] = value;
    }

    $.ajax({
        url: CONFIG_URL,
        method: "POST",
        async: false,
        success: function() {
            if (callbackFunc) {
                callbackFunc();
            }
        },
        error: function(xhr) {
            showConfigSaveError(xhr);
        },
        contentType: "application/json",
        data: JSON.stringify(data),
        dataType:"json"
    });
}


function setElementText(elemId, elemText) {
    var elem = document.getElementById(elemId);
    if (!hasInnerText) {
        elem.textContent = elemText;
    } else {
        elem.innerText = elemText;
    }
}


function updateCinCountElements() {
    $.get(CONFIG_URL + '?' + Date.now(), function(data, status) {
        cinCountList = data.cincount;
        setElementText('big5F', cinCountList['big5F']);
        setElementText('big5LF', cinCountList['big5LF']);
        setElementText('big5S', cinCountList['big5S']);
        setElementText('big5Other', cinCountList['big5Other']);
        setElementText('bopomofo', cinCountList['bopomofo']);
        setElementText('cjk', cinCountList['cjk']);
        setElementText('cjkExtA', cinCountList['cjkExtA']);
        setElementText('cjkExtB', cinCountList['cjkExtB']);
        setElementText('cjkExtC', cinCountList['cjkExtC']);
        setElementText('cjkExtD', cinCountList['cjkExtD']);
        setElementText('cjkExtE', cinCountList['cjkExtE']);
        setElementText('cjkExtF', cinCountList['cjkExtF']);
        setElementText('cjkCI', cinCountList['cjkCI']);
        setElementText('cjkCIS', cinCountList['cjkCIS']);
        setElementText('cjkOther', cinCountList['cjkOther']);
        setElementText('phrases', cinCountList['phrases']);
        setElementText('privateuse', cinCountList['privateuse']);
        setElementText('totalchardefs', cinCountList['totalchardefs']);
    }, "json");
}


// update checjConfig object with the value set by the user
function updateConfig() {
    // Preserve settings that are not shown on the current page.
    checjConfig = $.extend(true, {}, checjConfig);

    // Get values from checkboxes, text, hidden and radio
    $("input").each(function (index, inputItem) {
        if (inputItem.name == "") {
            return;
        }
        switch (inputItem.type) {
        case "checkbox":
            checjConfig[inputItem.name] = inputItem.checked;
            break;
        case "text":
        case "hidden":
        case "number":
            var inputValue = inputItem.value;
            if ($.isNumeric(inputValue)) {
                inputValue = parseInt(inputValue);
            } else if (typeof checjConfig[inputItem.name] === "number") {
                // 數字欄位被清空或打了非數字：沿用原值。以前會存成 ""，輸入法
                // 建立時 candidatePerRow 等設定變成字串，排版計算直接丟 TypeError
                break;
            }
            checjConfig[inputItem.name] = inputValue;
            break;
        case "radio":
            if (inputItem.checked === true) {
                checjConfig[inputItem.name] = parseInt(inputItem.value);
            }
            break;
        }
    });

    // Get values from select
    $("select").each(function (index, selectItem) {
        if (selectItem.value) {
            if ($(selectItem).data("value-type") === "string") {
                checjConfig[selectItem.name] = selectItem.value;
            }
            else {
                checjConfig[selectItem.name] = parseInt(selectItem.value);
            }
        }
    });

    if (checjConfig.candidateTheme) {
        checjConfig.candidateColors = {};
    }
}


function showSaveToast(message) {
    var toast = $("#settingsSaveToast");
    if (!toast.length) {
        toast = $("<div>").attr("id", "settingsSaveToast").addClass("settings-toast");
        $("body").append(toast);
    }
    toast.text(message);
    toast.addClass("show");
    clearTimeout(showSaveToast._timer);
    showSaveToast._timer = setTimeout(function() {
        toast.removeClass("show");
    }, 2200);
}

// 檢查一份文字資料的格式（規則在 js/data_format.js）。有錯時說明是哪一行，
// 切到該文字框所在的分頁並選取那一行，回傳 false
function checkDataFormat(checkData, checkType, elementId, dataDesc) {
    var error = findDataFormatError(checkData, checkType, imeFolderName);
    if (!error) {
        return true;
    }

    // 以前只在原地選取：錯誤若在沒開著的分頁，使用者得自己找是哪一頁
    var pane = $(elementId).closest(".tab-pane");
    var tabLink = pane.length ? $('#sidebar a[href="#' + pane.attr("id") + '"]')[0] : null;
    if (tabLink && window.bootstrap && bootstrap.Tab) {
        bootstrap.Tab.getOrCreateInstance(tabLink).show();
    }

    var lines = checkData.split("\n");
    var selectionStart = 0;
    for (var j = 0; j < error.line; j++) {
        selectionStart += lines[j].length + 1;
    }
    var selectErrorLine = function() {
        var textarea = $(elementId)[0];
        if (textarea) {
            textarea.focus();
            textarea.setSelectionRange(selectionStart, selectionStart + lines[error.line].length);
        }
    };
    selectErrorLine();

    // 行的內容是使用者的資料，可能含有 < 或 &，以文字插入
    var escapeHtml = function(text) {
        return $("<div>").text(text).html();
    };
    $.jAlert({
        'title': '糟糕！',
        'content': escapeHtml(dataDesc + '設定第 ' + (error.line + 1) + ' 行「' + error.text + '」格式錯誤！') +
            '<br>' + escapeHtml(error.reason),
        'theme': 'dark_red',
        'size': 'md',
        'blurBackground': true,
        'closeOnClick': true,
        'showAnimation': 'zoomIn',
        'hideAnimation': 'zoomOutDown',
        'btns': {'text': '關閉', 'theme': 'blue'},
        // 對話框打開時會拿走焦點；關掉後再選一次，那一行才看得到
        'onClose': selectErrorLine
    });
    return false;
}

// ── 排除聯想字詞：查詢 + 勾選 ────────────────────────────────────
var epPhraseData = null;  // 快取 phrase.json

function epParseExcluded() {
    var map = {};
    $("#excludePhrase").val().split("\n").forEach(function(line) {
        line = line.trim();
        if (!line) return;
        var eq = line.indexOf("=");
        if (eq < 1) return;
        var ch = line.substring(0, eq).trim();
        var phrases = line.substring(eq + 1).split(",").map(function(s){ return s.trim(); }).filter(Boolean);
        if (ch && phrases.length) map[ch] = phrases;
    });
    return map;
}

function epSaveExcluded(map) {
    var lines = [];
    Object.keys(map).forEach(function(ch) {
        if (map[ch] && map[ch].length) lines.push(ch + "=" + map[ch].join(","));
    });
    $("#excludePhrase").val(lines.join("\n")).trigger("change");
}

function epLoadPhraseJson(callback) {
    if (epPhraseData) { callback(epPhraseData); return; }
    $("#epSearchStatus").text("載入詞庫中…");
    $.getJSON("data/phrase.json", function(data) {
        epPhraseData = data;
        $("#epSearchStatus").text("");
        callback(data);
    }).fail(function() {
        $("#epSearchStatus").text("詞庫載入失敗");
    });
}

function epSearch() {
    var ch = $("#epSearchChar").val().trim();
    if (!ch) return;
    epLoadPhraseJson(function(data) {
        var candidates = (data.chardefs && data.chardefs[ch]) || [];
        if (!candidates.length) {
            $("#epSearchStatus").text("「" + ch + "」沒有內建聯想詞");
            $("#epResults").hide();
            epShowOtherExclusions(ch);
            return;
        }
        $("#epSearchStatus").text("");
        var excluded = epParseExcluded();
        var currentExcluded = excluded[ch] || [];
        epRenderCheckboxes(ch, candidates, currentExcluded);
        epShowOtherExclusions(ch);
    });
}

function epRenderCheckboxes(ch, candidates, currentExcluded) {
    var $box = $("#epCheckboxes").empty();
    candidates.forEach(function(p) {
        var isExcluded = currentExcluded.indexOf(p) !== -1;
        var id = "ep_cb_" + p;
        var $label = $("<label>")
            .addClass("ep-cb-label d-flex align-items-center gap-1 px-2 py-1 rounded user-select-none")
            .css({ cursor: "pointer", border: "1px solid", borderColor: isExcluded ? "var(--bs-danger)" : "var(--bs-secondary)", background: isExcluded ? "rgba(220,53,69,.12)" : "" });
        var $cb = $("<input>").attr({ type: "checkbox", id: id }).addClass("ep-cb").prop("checked", isExcluded);
        var $txt = $("<span>").text(p);
        $label.append($cb).append($txt);
        $label.on("click", function() {
            var checked = $cb.prop("checked");
            $label.css({ borderColor: checked ? "var(--bs-danger)" : "var(--bs-secondary)", background: checked ? "rgba(220,53,69,.12)" : "" });
        });
        $box.append($label);
    });
    $("#epResultsInfo").text("「" + ch + "」共有 " + candidates.length + " 個聯想詞，勾選的項目將被排除：");
    $("#epResults").show();
}

function epShowOtherExclusions(currentChar) {
    var excluded = epParseExcluded();
    var others = Object.keys(excluded).filter(function(c){ return c !== currentChar; });
    if (!others.length) { $("#epExistingOther").hide(); return; }
    var $list = $("#epExistingOtherList").empty();
    others.forEach(function(c) {
        var $chip = $("<span>")
            .addClass("badge text-bg-secondary me-1 mb-1")
            .css("cursor","pointer")
            .attr("title", "點擊查詢「" + c + "」")
            .text(c + "（" + excluded[c].length + "）")
            .on("click", function() {
                $("#epSearchChar").val(c);
                epSearch();
                document.getElementById("epResults").scrollIntoView({block:"nearest"});
            });
        $list.append($chip);
    });
    $("#epExistingOther").show();
}

function epApply() {
    var ch = $("#epSearchChar").val().trim();
    if (!ch) return;
    var excluded = epParseExcluded();
    var checked = [];
    $("#epCheckboxes .ep-cb:checked").each(function() {
        var phrase = $(this).closest("label").find("span").text();
        checked.push(phrase);
    });
    if (checked.length) excluded[ch] = checked;
    else delete excluded[ch];
    epSaveExcluded(excluded);
    var msg = checked.length ? "已排除 " + checked.length + " 個詞" : "已清除「" + ch + "」的排除設定";
    $("#epApplyMsg").text(msg).show().delay(2000).fadeOut();
    epShowOtherExclusions(ch);
}
// ─────────────────────────────────────────────────────────────────

function updateKeyboardLayout() {
    var radios = $('input[type=radio][name=keyboardLayout]');
    var radioval = 0;
    for (var i=0, len=radios.length; i<len; i++) {
        if (radios[i].checked) {
            radioval = radios[i].value;
            break;
        }
    }

    if(imeFolderName == "chephonetic") {
        switch (radioval) {
            case "0":
                $("#keyboard_preview").load("kblayout.htm #keyboard_chephonetic_layout0");
                break;
            case "1":
                $("#keyboard_preview").load("kblayout.htm #keyboard_chephonetic_layout1");
                break;
            case "2":
                $("#keyboard_preview").load("kblayout.htm #keyboard_chephonetic_layout2");
                break;
            case "3":
                $("#keyboard_preview").load("kblayout.htm #keyboard_chephonetic_layout3");
                break;
        }
    }
}


// jQuery ready
$(function() {
    // show PIME version number
    $("#version").load(VERSION_URL);
    // 只抓一次 config.htm，再於 client 端把各片段填入對應容器；
    // 原本對同一份 40KB 檔發了 14 次 .load()（14 趟往返、解析 14 遍）。
    // 每個片段仍各自 $.parseHTML 一份，語意與 jQuery .load(url + " #id") 一致。
    var fragmentTargets = [
        "#navbar_top", "#typing_page", "#intelligent_page", "#ui_page",
        "#keyboard_page", "#cin_count", "#cin_options", "#extendtable_page",
        "#symbols_page", "#fs_symbols_page", "#ez_symbols_page", "#phrase_page",
        "#flangs_page", "#navbar_bottom"
    ];
    $.get("config.htm", function(html) {
        fragmentTargets.forEach(function(sel) {
            $(sel).html($("<div>").append($.parseHTML(html)).find(sel));
        });
    }, "html");
    pageWait();
});

function pageWait() {
    if (configLoadFailed) {
        return; // 橫幅已說明原因；不要再無限輪詢
    }
    if (document.getElementById("ok") && configLoaded) {
        pageReady();
    }
    else
    {
        window.setTimeout(pageWait,100);
    }
}

function pageReady() {
    updateCinCountElements();
    // Bootstrap 5：popover 改用原生 API 初始化
    if (window.bootstrap && bootstrap.Popover) {
        document.querySelectorAll('[data-bs-toggle="popover"]').forEach(function(el) {
            new bootstrap.Popover(el);
        });
    }

    $("#symbols").val(symbolsData);
    $("#ez_symbols").val(swkbData);
    $("#fs_symbols").val(fsymbolsData);
    $("#phrase").val(phraseData);
    $("#excludePhrase").val(excludePhraseData);
    epShowOtherExclusions("");
    $("#flangs").val(flangsData);
    $("#extendtable").val(extendtableData);

    $("#fontSize").TouchSpin({min:6, max:200});
    $("#candidatePerRow").TouchSpin({min:1, max:10});
    $("#candidateMinWidth").TouchSpin({min:160, max:720});
    $("#candidateMaxWidth").TouchSpin({min:220, max:720});

    var selWhichShift = [
        "左右兩邊都使用",
        "僅使用左 Shift",
        "僅使用右 Shift"
    ];
    var switchLangWithWhichShift = $("#switchLangWithWhichShift");
    for(var i = 0; i < selWhichShift.length; ++i) {
        var selWhichShiftOption = selWhichShift[i];
        var item = '<option value="' + i + '">' + selWhichShiftOption + '</option>';
        switchLangWithWhichShift.append(item);
    }
    switchLangWithWhichShift.children().eq(checjConfig.switchLangWithWhichShift).prop("selected", true);


    var candidateTheme = $("#candidateTheme");
    for(var i = 0; i < candidateThemeNames.length; ++i) {
        var themeName = candidateThemeNames[i];
        var item = '<option value="' + themeName + '">' + themeName + '</option>';
        candidateTheme.append(item);
    }
    candidateTheme.val(checjConfig.candidateTheme || "System");

    var selPositionModes = [
        "跟隨游標",
        "螢幕下緣置中"
    ];
    var candidatePositionMode = $("#candidatePositionMode");
    for(var i = 0; i < selPositionModes.length; ++i) {
        var item = '<option value="' + i + '">' + selPositionModes[i] + '</option>';
        candidatePositionMode.append(item);
    }
    candidatePositionMode.children().eq(checjConfig.candidatePositionMode || 0).prop("selected", true);

    $("#candidateKeyStyle").val(checjConfig.candidateKeyStyle || "word-first");
    $("#candidateHeaderStyle").val(checjConfig.candidateHeaderStyle || "accent");
    $("#candidateMessageStyle").val(checjConfig.candidateMessageStyle || "badge");
    $("#candidateMessageBehavior").val(checjConfig.candidateMessageBehavior || "progressive");

    var selCinType = $("#selCinType");
    for(var i = 0; i < selCins.length; ++i) {
        var selCin = selCins[i];
        var item = '<option value="' + i + '">' + selCin + '</option>';
        selCinType.append(item);
    }
    selCinType.children().eq(checjConfig.selCinType).prop("selected", true);

    var selRCinType = $("#selRCinType");
    for(var i = 0; i < selRCins.length; ++i) {
        // 沒有安裝碼表檔的不列出（精簡安裝檔只附大易、倉頡、注音系列），選了也反查不到
        if (rcinAvailable && rcinAvailable.length && rcinAvailable.indexOf(i) < 0) {
            continue;
        }
        var selRCin = selRCins[i];
        var item = '<option value="' + i + '">' + selRCin + '</option>';
        selRCinType.append(item);
    }
    if (selRCinType.find('option[value="' + checjConfig.selRCinType + '"]').length) {
        selRCinType.val(String(checjConfig.selRCinType));
    } else {
        selRCinType.children().first().prop("selected", true);
    }

    var selHCinType = $("#selHCinType");
    for(var i = 0; i < selHCins.length; ++i) {
        var selHCin = selHCins[i];
        var item = '<option value="' + i + '">' + selHCin + '</option>';
        selHCinType.append(item);
    }
    selHCinType.children().eq(checjConfig.selHCinType).prop("selected", true);

    var selWildcards=[
        "Ｚ　",
        "＊　"
    ];
    var selWildcardType = $("#selWildcardType");
    for(var i = 0; i < selWildcards.length; ++i) {
        var selWildcard = selWildcards[i];
        var item = '<option value="' + i + '">' + selWildcard + '</option>';
        selWildcardType.append(item);
    }
    selWildcardType.children().eq(checjConfig.selWildcardType).prop("selected", true);

    var keyboard_ddmenu = $("#keyboard_ddmenu");
    if(imeFolderName == "chephonetic") {
        keyboard_ddmenu.show();
    }

    var keyboard_page = $("#keyboard_layout");
    for(var i = 0; i < keyboardNames.length; ++i) {
        var id = "kb" + i;
        var name = keyboardNames[i];
        var item = '<div class="col-xs-6 col-sm-6 col-md-3 col-lg-3"><input type="radio" id="' + id + '" name="keyboardLayout" value="' + i + '">' +
            '<label for="' + id + '">' + name + '</label></div>';
        keyboard_page.append(item);
    }
    $("#kb" + checjConfig.keyboardLayout).prop("checked", true);
    updateKeyboardLayout();

    if(imeFolderName == "chedayi") {
        var selDayiSymbolChars=[
            "＝　",
            "號　"
        ];
        var selDayiSymbolCharType = $("#selDayiSymbolCharType");
        for(var i = 0; i < selDayiSymbolChars.length; ++i) {
            var selDayiSymbolChar = selDayiSymbolChars[i];
            var item = '<option value="' + i + '">' + selDayiSymbolChar + '</option>';
            selDayiSymbolCharType.append(item);
        }
        selDayiSymbolCharType.children().eq(checjConfig.selDayiSymbolCharType).prop("selected", true);
    }

    $("#symbols").change(function(){
        symbolsChanged = true;
    });

    $("#ez_symbols").change(function(){
        swkbChanged = true;
    });

    $("#fs_symbols").change(function(){
        fsymbolsChanged = true;
    });

    $("#phrase").change(function(){
        phraseChanged = true;
    });

    $("#excludePhrase").change(function(){
        excludePhraseChanged = true;
    });

    // 排除聯想字詞：查詢 + 勾選事件
    $("#epSearchBtn").on("click", epSearch);
    $("#epSearchChar").on("keydown", function(e) { if (e.key === "Enter") epSearch(); });
    $("#epApplyBtn").on("click", epApply);

    $("#flangs").change(function(){
        flangsChanged = true;
    });

    $("#extendtable").change(function(){
        extendtableChanged = true;
        $("#reLoadTable")[0].checked = true;
    });

    // OK button
    $("#ok").on('click', function () {
        updateConfig(); // update the config based on the state of UI elements
        saveConfig(function() {
            // 成功提示用自動消失的 toast，不打斷操作；錯誤仍用對話框
            $("#unsavedHint").hide();
            showSaveToast("設定已套用");
        });
        updateCinCountElements();
        return false;
    });

    // set all initial values
    $("input").each(function(index, elem) {
        var item = $(this);
        var value = checjConfig[item.attr("id")];
        switch(item.attr("type")) {
        case "checkbox":
            item.prop("checked", value);
            break;
        case "text":
            item.val(value);
            break;
        }
    });

    // setup switchLangWithWhichShift default disabled property
    $("#switchLangWithWhichShift").prop("disabled", !checjConfig["switchLangWithShift"]);

    // when switchLangWithShift changes, update switchLangWithWhichShift disabled property
    $("#switchLangWithShift").on("click", function() {
        $("#switchLangWithWhichShift").prop("disabled", !this.checked);
    });

    // Phase 0: 父項關閉時，自動停用（並變灰）相依的子選項與下拉
    function bindDependentEnable(parentId, dependents) {
        var $parent = $("#" + parentId);
        if (!$parent.length) {
            return;
        }
        function apply() {
            var on = $parent.prop("checked");
            dependents.forEach(function(dep) {
                $("#" + dep.field).prop("disabled", !on);
                if (dep.item) {
                    $("#" + dep.item).toggleClass("is-disabled", !on);
                }
            });
        }
        apply();
        $parent.on("click", apply);
    }

    // selWildcardType / selRCinType / selHCinType 的停用狀態由 disableControlItem()
    // 同時考量「碼表相容性」與「對應功能核取是否開啟」；見該函式末端的相依連動。
    bindDependentEnable("intelligentSelect", [
        { field: "intelligentSelectRecent", item: "intelligentSelectRecent_item" },
        { field: "intelligentSelectContext", item: "intelligentSelectContext_item" }
    ]);

    // Phase 0: 未儲存變更提示。configReady 在初始化完成後才設為 true，
    // 避免載入階段程式設定值時誤觸發。
    var configReady = false;
    function markUnsaved() {
        if (configReady) {
            $("#unsavedHint").show();
        }
    }
    $("body").on("change", "input:not(#settingsSearch), select, textarea", markUnsaved);

    // Phase 2: 側欄分區搜尋。以 class 切換顯示，保留 intelligent/keyboard
    // 等項目原本的條件隱藏（inline display:none）不被搜尋誤開啟。
    $("#settingsSearch").on("input", function() {
        var q = $.trim($(this).val()).toLowerCase();
        $(".sidebar-nav > li").not(".sidebar-heading").each(function() {
            var li = $(this);
            var match = (q === "") || (li.text().toLowerCase().indexOf(q) !== -1);
            li.toggleClass("search-hidden", !match);
        });
        $(".sidebar-nav > li.sidebar-heading").each(function() {
            var heading = $(this);
            var anyVisible = false;
            heading.nextUntil(".sidebar-heading").each(function() {
                var it = $(this);
                if (!it.hasClass("search-hidden") && it.css("display") !== "none") {
                    anyVisible = true;
                    return false;
                }
            });
            heading.toggleClass("search-hidden", !((q === "") || anyVisible));
        });
    });

    // trigger event
    $('.ui-spinner-button').click(function() {
        $(this).siblings('input').change();
    });

    $("#ui_page input").on("change", updateCandidateAppearanceGalleries);

    $("#ui_page input").on("keydown", function(e) {
        if (e.keyCode == 38 || e.keyCode==40) {
            updateCandidateAppearanceGalleries();
        }
    });
    $("#candidateTheme, #candidateKeyStyle, #candidateHeaderStyle, #candidateMessageStyle, #candidateMessageBehavior").on("change", updateCandidateAppearanceGalleries);
    $("#candidateThemeGrid").on("click", ".candidate-theme-card", function() {
        $("#candidateTheme").val($(this).data("theme"));
        updateCandidateAppearanceGalleries();
    });
    $("#candidateKeyStyleGrid").on("click", ".candidate-style-card", function() {
        $("#candidateKeyStyle").val($(this).data("style"));
        updateCandidateAppearanceGalleries();
    });
    $("#candidateMessageStyleGrid").on("click", ".candidate-message-style-card", function() {
        $("#candidateMessageStyle").val($(this).data("style"));
        updateCandidateAppearanceGalleries();
    });
    $("#candidateHeaderStyleGrid").on("click", ".candidate-header-style-card", function() {
        $("#candidateHeaderStyle").val($(this).data("style"));
        updateCandidateAppearanceGalleries();
    });
    $("#candidateMessageBehaviorGrid").on("click", ".candidate-message-behavior-card", function() {
        $("#candidateMessageBehavior").val($(this).data("behavior"));
        updateCandidateAppearanceGalleries();
    });
    renderCandidateMessageBehaviorGallery();
    renderCandidateMessageStyleGallery();
    renderCandidateHeaderStyleGallery();
    renderCandidateKeyStyleGallery();
    renderCandidateThemeGallery();
    updateCandidateAppearanceGalleries();

    // 某個碼表停用項目時，說明文字改成停用的原因；換回其他碼表時還原
    function setDisabledReason(id, reason) {
        var hint = $("#" + id).nextAll(".setting-hint").first();
        if (!hint.length) {
            return;
        }
        if (hint.data("originalText") === undefined) {
            hint.data("originalText", hint.text());
        }
        hint.text(reason || hint.data("originalText"));
    }

    function disableControlItem() {
        var disabled = []
        for(key in disableConfigItem) {
            if (checjConfig.selCinType == key) {
                if (disabled.indexOf(disableConfigItem[key][0]) < 0) {
                    if (disableConfigItem[key][1] != null) {
                        $('#' + disableConfigItem[key][0])[0].checked = disableConfigItem[key][1];
                    }
                    $('#' + disableConfigItem[key][0])[0].disabled = true;
                    setDisabledReason(disableConfigItem[key][0], disableConfigItem[key][2]);
                    disabled.push(disableConfigItem[key][0])
                }
            } else if (key > 100) {
                if (disableConfigItem[key][1] != null) {
                    $('#' + disableConfigItem[key][0])[0].checked = disableConfigItem[key][1];
                }
                $('#' + disableConfigItem[key][0])[0].disabled = true;
            } else {
                if (disabled.indexOf(disableConfigItem[key][0]) < 0) {
                    $('#' + disableConfigItem[key][0])[0].disabled = false;
                    setDisabledReason(disableConfigItem[key][0], null);
                }
            }
        }

        if ($('#compositionBufferMode')[0].checked == false) {
            $("#autoMoveCursorInBrackets")[0].disabled = true;
        } else {
            $("#autoMoveCursorInBrackets")[0].disabled = false;
        }

        if ($('#fullShapeSymbols')[0].checked == false) {
            $("#directOutFSymbols")[0].disabled = true;
        } else {
            $("#directOutFSymbols")[0].disabled = false;
        }

        if ($('#selWildcardType')[0].disabled == true) {
            $("#selWildcardType").val(1);
        }

        // 相依下拉：停用狀態 = 碼表相容邏輯停用 或 對應功能核取關閉（雙向）。
        // 讓「功能關閉→右側下拉無作用」直接以變灰呈現，開啟時再回復可用。
        // 只有 selWildcardType 受碼表管理（大易恆停用）；另兩者純由核取決定。
        // 放在 selWildcardType val 重設之後，避免因核取停用而誤重設使用者選值。
        [["supportWildcard", "selWildcardType"],
         ["imeReverseLookup", "selRCinType"],
         ["homophoneQuery", "selHCinType"]].forEach(function(pair) {
            var cb = document.getElementById(pair[0]);
            var sel = document.getElementById(pair[1]);
            if (!cb || !sel) return;
            var tableDisabled = (pair[1] === "selWildcardType") ? sel.disabled : false;
            sel.disabled = tableDisabled || !cb.checked;
        });
    }

    disableControlItem();

    // 所有碼表都停用的項目（例如大易的空白鍵換頁）直接藏起來，不留一個永遠反灰的選項；
    // 下拉選單（例如大易固定用 ＊ 的萬用字元鍵）改成顯示固定的文字
    function hideItemsDisabledForAllTables() {
        for (var key in disableConfigItem) {
            if (key <= 100) {
                continue;
            }
            var elem = $("#" + disableConfigItem[key][0]);
            if (!elem.length || elem.hasClass("config-item-hidden")) {
                continue;
            }
            if (elem.is("select")) {
                var text = $.trim(elem.find(":selected").text());
                elem.addClass("config-item-hidden").hide();
                $("<span>").addClass("config-fixed-value").text(text).insertAfter(elem);
            } else {
                // 核取方塊、它的標籤、說明圖示與說明文字（到下一個輸入項之前）
                elem.add(elem.nextUntil("input")).addClass("config-item-hidden").hide();
            }
        }
    }
    hideItemsDisabledForAllTables();

    // 功能核取切換時，即時更新其相依下拉的停用狀態
    $("#supportWildcard, #imeReverseLookup, #homophoneQuery").on("click", disableControlItem);

    $('#compositionBufferMode').click(function() {
        if ($('#compositionBufferMode')[0].checked == false) {
            $("#autoMoveCursorInBrackets")[0].disabled = true;
        } else {
            $("#autoMoveCursorInBrackets")[0].disabled = false;
        }
    });

    $('#fullShapeSymbols').click(function() {
        if ($('#fullShapeSymbols')[0].checked == false) {
            $("#directOutFSymbols")[0].disabled = true;
        } else {
            $("#directOutFSymbols")[0].disabled = false;
        }
    });

    $("#selCinType").change(function() {
        var selCin = parseInt($("#selCinType").find(":selected").val());
        if(!isNaN(selCin))
            checjConfig.selCinType = selCin;
        disableControlItem();
    });


    $('input[type=radio][name=keyboardLayout]').change(function() {
        updateKeyboardLayout();
    });

    if(!debugMode) {
        $("#compositionBufferMode")[0].disabled = true;
        $("#autoMoveCursorInBrackets")[0].disabled = true;
        $("#compositionBufferMode")[0].checked = false;
        $("#autoMoveCursorInBrackets")[0].checked = false;
    } else {
        $('#intelligent_ddmenu').show();
    }


    // keep the server alive every 20 second
    setInterval(function () {
        $.ajax({
            url: KEEP_ALIVE_URL + '?' + Date.now()
        });
    }, 20 * 1000);

    // 初始化完成，之後使用者的變更才會觸發「尚未儲存」提示
    configReady = true;
}
