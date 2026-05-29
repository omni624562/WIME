
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
var configLoaded = false;
var CONFIG_URL = '/config';
var VERSION_URL = '/version.txt';
var KEEP_ALIVE_URL = '/keep_alive';
var hasInnerText = (document.getElementsByTagName("body")[0].innerText !== undefined) ? true : false;

var symbolsChanged = false;
var swkbChanged = false;
var fsymbolsChanged = false;
var phraseChanged = false;
var flangsChanged = false;
var extendtableChanged = false;

var symbolsData = "";
var swkbData = "";
var fsymbolsData = "";
var phraseData = "";
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
        symbolsData = data.symbols;
        swkbData = data.swkb;
        fsymbolsData = data.fsymbols;
        phraseData = data.phrase;
        flangsData = data.flangs;
        extendtableData = data.extendtable;
        configLoaded = true;
    }, "json");
}
loadConfig();

function applyCandidateDefaults() {
    var currentIme = typeof imeFolderName !== "undefined" ? imeFolderName : "";
    var modernDefaultIme = ["chedayi", "checj", "cheliu"].indexOf(currentIme) >= 0;
    if (!modernDefaultIme) {
        return;
    }
    if (typeof checjConfig.candidateModernStyle === "undefined") {
        checjConfig.candidateModernStyle = true;
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
    if (typeof checjConfig.candidateMaxWidth === "undefined" || checjConfig.candidateMaxWidth < 220) {
        checjConfig.candidateMaxWidth = 340;
    }
    if (typeof checjConfig.candidateTheme === "undefined") {
        checjConfig.candidateTheme = "Night Comfort";
    }
    if (typeof checjConfig.candidatePerRow === "undefined") {
        checjConfig.candidatePerRow = 10;
    }
    if (typeof checjConfig.candidateEdgeAvoidance === "undefined") {
        checjConfig.candidateEdgeAvoidance = true;
    }
}

var candidateThemeNames = [
    "Night Comfort",
    "Soft Focus",
    "Warm Gray",
    "Graphite",
    "Slate Teal",
    "Olive",
    "Plum",
    "Amber",
    "Light",
    "Paper",
    "Mist Light",
    "Sepia Dim"
];

var candidateThemePalette = {
    "Night Comfort": ["#1b1c20", "#4a4d57", "#30323a", "#e5e8ee", "#a9afba", "#b8c7e8", "#405f8a", "#5e7ea7", "#eef4ff", "#aeb9cf"],
    "Soft Focus": ["#191d21", "#44525a", "#2b343a", "#e4ebee", "#a8b5ba", "#9cc8bd", "#3f6f6b", "#6a9993", "#ecfbf8", "#a4bcb6"],
    "Warm Gray": ["#20201d", "#58554b", "#39372f", "#ebe7dc", "#b7b1a3", "#d7c48e", "#5f684d", "#87936f", "#f7f3e7", "#c1b8a2"],
    "Graphite": ["#12141a", "#444a57", "#292e38", "#f3f5fa", "#aeb5c4", "#8fb3ff", "#4169d7", "#6f92eb", "#edf3ff", "#9eb0d5"],
    "Slate Teal": ["#152027", "#3f5a64", "#263943", "#f0f8fb", "#a5bac2", "#87d4dd", "#2f7f9f", "#60adc8", "#e9fbff", "#98c2ca"],
    "Olive": ["#171b16", "#4b5941", "#2c3328", "#f4f7ef", "#b4bda7", "#b6df88", "#5d7f36", "#91b962", "#f4ffe8", "#b9c8a8"],
    "Plum": ["#1d1721", "#604b66", "#382c3e", "#fbf4ff", "#c0adca", "#e0a7ff", "#7a55b8", "#aa83e6", "#fbf3ff", "#c5a9d1"],
    "Amber": ["#211a12", "#68533a", "#3c2f22", "#fff8ed", "#cfbda4", "#ffc46f", "#9a6730", "#d59a58", "#fff3de", "#d4baa0"],
    "Light": ["#f7f9fc", "#aeb8cb", "#dbe2ed", "#182235", "#657187", "#2f66dc", "#2f6eea", "#1d56c4", "#ffffff", "#44639a"],
    "Paper": ["#fbfaf6", "#b7ac9c", "#e4ded4", "#272119", "#786b5d", "#8a4f17", "#315f87", "#244967", "#f7fbff", "#6f665c"],
    "Mist Light": ["#e9edf0", "#a8b3bc", "#d4dce1", "#24303a", "#66727d", "#426b85", "#5f7f94", "#4b687b", "#f7fbfd", "#577385"],
    "Sepia Dim": ["#28251f", "#5d564a", "#403a31", "#ebe2d3", "#b9ad9a", "#dfc58e", "#6d6547", "#958a63", "#f8efd9", "#c7b79e"]
};

function getCandidatePreviewSample() {
    var previewName = checjConfig.imeDisplayName || "大易";
    var root = "月";
    var candidates = ["明", "朋", "服", "朗", "朝", "朔", "期", "望", "有", "肚"];

    if (imeFolderName == "checj") {
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
        candidates: candidates
    };
}

function applyCandidatePreviewTheme(preview, theme, modern) {
    preview.css({
        "background-color": modern ? theme[0] : "#ffffff",
        "border-color": modern ? theme[1] : "#000000",
        "border-radius": modern ? "6px" : "0",
        "color": modern ? theme[3] : "#000000"
    });
    preview.find(".candidate-preview-header").css("border-bottom-color", modern ? theme[2] : "#d0d0d0");
    preview.find(".candidate-preview-name, .candidate-preview-page").css("color", modern ? theme[4] : "#0000b4");
    preview.find(".candidate-preview-root").css("color", modern ? theme[5] : "#0000b4");
    preview.find(".candidate-preview-item span").css("color", modern ? theme[9] : "#0000ff");
    preview.find(".candidate-preview-item.active").css({
        "background-color": modern ? theme[6] : "#000000",
        "border-color": modern ? theme[7] : "#000000",
        "border-radius": modern ? "6px" : "0",
        "color": modern ? theme[8] : "#ffffff"
    });
    preview.find(".candidate-preview-item.active span").css("color", modern ? theme[8] : "#ffffff");
}

function fillCandidatePreviewItems(preview, sample) {
    var count = parseInt($("#candidatePerRow").val(), 10) || 4;
    count = Math.max(1, Math.min(count, 10));
    var body = preview.find(".candidate-preview-body");
    body.empty();

    for (var i = 0; i < count; ++i) {
        var item = $("<span>").addClass("candidate-preview-item");
        if (i == 0) {
            item.addClass("active");
        }
        item.append($("<span>").text((i + 1).toString().slice(-1)));
        item.append(document.createTextNode(sample.candidates[i % sample.candidates.length]));
        body.append(item);
    }
}

function candidatePreviewFontSize() {
    var fontSize = parseInt($("#fontSize").val(), 10) || 12;
    return Math.max(6, Math.min(fontSize, 48));
}

function createCandidatePreview(sample) {
    var preview = $("<div>").addClass("candidate-preview");
    var header = $("<div>").addClass("candidate-preview-header");
    header.append($("<span>").addClass("candidate-preview-name").text(sample.name));
    header.append($("<span>").addClass("candidate-preview-root").text(sample.root));
    header.append($("<span>").addClass("candidate-preview-page").text("1/1"));
    preview.append(header);
    preview.append($("<div>").addClass("candidate-preview-body"));
    fillCandidatePreviewItems(preview, sample);
    return preview;
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

function updateCandidateThemeGallery() {
    var grid = $("#candidateThemeGrid");
    if (!grid.length) {
        return;
    }

    var selectedTheme = $("#candidateTheme").val() || "Night Comfort";
    var modern = $("#candidateModernStyle").prop("checked");
    var stableWidth = $("#candidateStableWidth").prop("checked");
    var wrapToMaxWidth = $("#candidateWrapToMaxWidth").prop("checked");
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
        applyCandidatePreviewTheme(preview, candidateThemePalette[themeName] || candidateThemePalette["Night Comfort"], modern);
    });
}

function saveConfig(callbackFunc) {
    var checkState = true
    // Check symbols format
    checkState = checkDataFormat($("#symbols").val(), "2", "#symbols", "特殊符號");
    if (!checkState) {
        return false;
    }

    // Check easy symbols format
    checkState = checkDataFormat($("#ez_symbols").val(), "1", "#ez_symbols", "簡易符號");
    if (!checkState) {
        return false;
    }

    // Check fullshape symbols format
    checkState = checkDataFormat($("#fs_symbols").val(), "2", "#fs_symbols", "全形標點符號");
    if (!checkState) {
        return false;
    }

    // Check user phrase format
    checkState = checkDataFormat($("#phrase").val(), "2", "#phrase", "聯想字詞");
    if (!checkState) {
        return false;
    }

    // Check foreign language format
    checkState = checkDataFormat($("#flangs").val(), "2", "#flangs", "外語文字");
    if (!checkState) {
        return false;
    }

    // Check extendtable format
    checkState = checkDataFormat($("#extendtable").val(), "3", "#extendtable", "擴展碼表");
    if (!checkState) {
        return false;
    }

    var data = {
        "config": checjConfig
    }

    if(symbolsChanged) {
        data.symbols = $("#symbols").val();
    }
    if(swkbChanged) {
        data.swkb = $("#ez_symbols").val();
    }
    if(fsymbolsChanged) {
        data.fsymbols = $("#fs_symbols").val();
    }
    if(phraseChanged) {
        data.phrase = $("#phrase").val();
    }
    if(flangsChanged) {
        data.flangs = $("#flangs").val();
    }
    if(extendtableChanged) {
        data.extendtable = $("#extendtable").val();
    }

    $.ajax({
        url: CONFIG_URL,
        method: "POST",
        async: false,
        success: callbackFunc(),
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


function checkDataFormat(checkData, checkType, elementId, dataDesc) {
    var data_array = checkData.split("\n");
    var errorState = false;
    for (var i = 0; i < data_array.length; i++) {
        switch (checkType) {
            case "1":
                if (! /^[A-Za-z] .{1,10}$/.test(data_array[i])) {
                    errorState = true;
                    $.jAlert({
                        'title': '糟糕！',
                        'content': dataDesc + '設定第 ' + (i + 1) + ' 行「'+ data_array[i] +'」格式錯誤！<br>請使用「英文 + 空格 + 符號」的格式。',
                        'theme': 'dark_red',
                        'size': 'md',
                        'blurBackground': true,
                        'closeOnClick': true,
                        'showAnimation': 'zoomIn',
                        'hideAnimation': 'zoomOutDown',
                        'btns': {'text': '關閉', 'theme': 'blue'}
                    });
                }
                break;
            case "2":
                if (data_array[i].length > 1 && data_array[i].search("=") == -1) {
                    errorState = true;
                    $.jAlert({
                        'title': '糟糕！',
                        'content': dataDesc + '設定第 ' + (i + 1) + ' 行格式錯誤！<br>單行不能超過一個字元，或是沒有 = 符號區隔。',
                        'theme': 'dark_red',
                        'size': 'md',
                        'blurBackground': true,
                        'closeOnClick': true,
                        'showAnimation': 'zoomIn',
                        'hideAnimation': 'zoomOutDown',
                        'btns': {'text': '關閉', 'theme': 'blue'}
                    });
                }
                break;
            case "3":
                if (! /^[A-Za-z\d]+ .{1,40}$/.test(data_array[i])) {
                    if (!(data_array.length == 1 && data_array[0].length == 0))
                    {
                        errorState = true;
                        if (data_array[i].length == 0) {
                            alertContent = dataDesc + '設定第 ' + (i + 1) + ' 行為空行！<br>請去除該空行或使用「英數 + 空格 + 字詞」的格式。'
                        }
                        else {
                            alertContent = dataDesc + '設定第 ' + (i + 1) + ' 行「'+ data_array[i] +'」格式錯誤！<br>請使用「英數 + 空格 + 字詞」的格式。'
                        }

                        $.jAlert({
                            'title': '糟糕！',
                            'content': alertContent,
                            'theme': 'dark_red',
                            'size': 'md',
                            'blurBackground': true,
                            'closeOnClick': true,
                            'showAnimation': 'zoomIn',
                            'hideAnimation': 'zoomOutDown',
                            'btns': {'text': '關閉', 'theme': 'blue'}
                        });
                    }
                }
                break;
        }
        if (errorState) {
            $(elementId).blur();
            // Count select range
            var selectionStart = 0;
            for (var j = 0; j < i; j++) {
                selectionStart += data_array[j].length + 1;
            }

            $(elementId).prop("selectionStart", selectionStart);
            $(elementId).prop("selectionEnd", selectionStart + data_array[i].length + 1);
            return false;
        }
    }
    return true;
}


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
    $("#tabs").hide();
    $("#version").load(VERSION_URL);
    $("#navbar_top").load("config.htm #navbar_top");
    $("#typing_page").load("config.htm #typing_page");
    $("#intelligent_page").load("config.htm #intelligent_page");
    $("#ui_page").load("config.htm #ui_page");
    $("#keyboard_page").load("config.htm #keyboard_page");
    $("#cin_count").load("config.htm #cin_count");
    $("#cin_options").load("config.htm #cin_options");
    $("#extendtable_page").load("config.htm #extendtable_page");
    $("#symbols_page").load("config.htm #symbols_page");
    $("#fs_symbols_page").load("config.htm #fs_symbols_page");
    $("#ez_symbols_page").load("config.htm #ez_symbols_page");
    $("#phrase_page").load("config.htm #phrase_page");
    $("#flangs_page").load("config.htm #flangs_page");
    $("#navbar_bottom").load("config.htm #navbar_bottom");
    pageWait();
});

function pageWait() {
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
    $('[data-toggle="popover"]').popover()

    $("#symbols").val(symbolsData);
    $("#ez_symbols").val(swkbData);
    $("#fs_symbols").val(fsymbolsData);
    $("#phrase").val(phraseData);
    $("#flangs").val(flangsData);
    $("#extendtable").val(extendtableData);

    if (imeFolderName == "chedayi") {
        $("#candPerRow").TouchSpin({min:1, max:6});
        $("#candPerPage").TouchSpin({min:1, max:6});
    }
    else {
        $("#candPerRow").TouchSpin({min:1, max:10});
        $("#candPerPage").TouchSpin({min:1, max:10});
    }
    $("#candMaxItems").TouchSpin({min:100, max:10000});
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

    var selMessageTimes=[
        "０　",
        "１　",
        "２　",
        "３　",
        "４　",
        "５　"
    ];
    var messageDurationTime = $("#messageDurationTime");
    for(var i = 0; i < selMessageTimes.length; ++i) {
        var selMessageTime = selMessageTimes[i];
        var item = '<option value="' + i + '">' + selMessageTime + '</option>';
        messageDurationTime.append(item);
    }
    messageDurationTime.children().eq(checjConfig.messageDurationTime).prop("selected", true);

    var candidateTheme = $("#candidateTheme");
    for(var i = 0; i < candidateThemeNames.length; ++i) {
        var themeName = candidateThemeNames[i];
        var item = '<option value="' + themeName + '">' + themeName + '</option>';
        candidateTheme.append(item);
    }
    candidateTheme.val(checjConfig.candidateTheme || "Night Comfort");

    var selCinType = $("#selCinType");
    for(var i = 0; i < selCins.length; ++i) {
        var selCin = selCins[i];
        var item = '<option value="' + i + '">' + selCin + '</option>';
        selCinType.append(item);
    }
    selCinType.children().eq(checjConfig.selCinType).prop("selected", true);

    var selRCinType = $("#selRCinType");
    for(var i = 0; i < selRCins.length; ++i) {
        var selRCin = selRCins[i];
        var item = '<option value="' + i + '">' + selRCin + '</option>';
        selRCinType.append(item);
    }
    selRCinType.children().eq(checjConfig.selRCinType).prop("selected", true);

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
            $.jAlert({
            'title': '好耶！',
            'content': '設定成功儲存！',
            'theme': 'blue',
            'size': 'md',
            'blurBackground': true,
            'closeOnClick': true,
            'showAnimation': 'zoomIn',
            'hideAnimation': 'zoomOutDown',
            'btns': {'text': '關閉', 'theme': 'blue'}
            });
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

    // use for select example
    function updateSelExample() {
        var example = ["選", "字", "大", "小", "範", "例"];
        var html="";

        for (number = 1, i = 0, row = 0; number <= $("#candPerPage").val(); number++, i++, row++) {
            if (example[i] == null) {
                i = 0;
            }

            if (row == $("#candPerRow").val()) {
                row = 0;
                html += "<br>";
            }

            html += "<span>" + number.toString().slice(-1) + ".</span> " + example[i] + "&nbsp;&nbsp;";
        }

        $("#selExample").html(html);
    }

    // setup selExample default style
    $("#selExample").css("font-size", $("#fontSize").val() + "pt");
    updateSelExample();

    // trigger event
    $('.ui-spinner-button').click(function() {
        $(this).siblings('input').change();
    });

    $("#ui_page input").on("change", function() {
        $("#selExample").css("font-size", $("#fontSize").val() + "pt");
        updateSelExample();
        updateCandidateThemeGallery();
    });

    $("#ui_page input").on("keydown", function(e) {
        if (e.keyCode == 38 || e.keyCode==40) {
            $("#selExample").css("font-size", $("#fontSize").val() + "pt");
            updateSelExample();
            updateCandidateThemeGallery();
        }
    });
    $("#candidateTheme").on("change", updateCandidateThemeGallery);
    $("#candidateThemeGrid").on("click", ".candidate-theme-card", function() {
        $("#candidateTheme").val($(this).data("theme"));
        updateCandidateThemeGallery();
    });
    renderCandidateThemeGallery();
    updateCandidateThemeGallery();

    function disableControlItem() {
        var disabled = []
        for(key in disableConfigItem) {
            if (checjConfig.selCinType == key) {
                if (disabled.indexOf(disableConfigItem[key][0]) < 0) {
                    if (disableConfigItem[key][1] != null) {
                        $('#' + disableConfigItem[key][0])[0].checked = disableConfigItem[key][1];
                    }
                    $('#' + disableConfigItem[key][0])[0].disabled = true;
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
    }

    disableControlItem();

    // trigger event
    $('#navbars ul li a').click(function(){
        if($('.navbar-toggle').css('display') != 'none' && $(this).attr('href') != '#') {
            $('.navbar-toggle').click();
        }
    });

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
}
