// 大易/酷倉等 CIN 輸入法設定頁的文字資料格式檢查：簡易符號、擴展碼表，以及
// 「名稱=內容」格式的特殊符號、全形標點、聯想字詞、外語文字。
//
// 這裡只判斷、不碰 DOM：js/config.js 的 checkDataFormat() 負責顯示錯誤、切到
// 該分頁並選取有問題的那一行；tests/test_config_pages.py 用 node 直接驗證規則。
// 規則跟著後端讀檔的程式走（cinbase/swkb.py、extendtable.py、symbols.py 等）：
// 後端會去掉的 BOM 與行首行尾空白、會略過的空行，這裡也不能擋。以前檔案結尾
// 多一個換行（空行）就擋住「套用設定」，連主題、字型等無關的設定都存不了。

// 各輸入法所有碼表 %keyname 的聯集，也就是打得出來的編碼字元（後端會把擴展碼表
// 的編碼轉成小寫）。編碼含有其他字元（全形字、打錯的符號）就永遠打不出來，存檔
// 前先擋下。以前只收英數，大易的 , . / ; ' [ ] - = \ ` 字根都被當成格式錯誤，
// 約四分之一的大易編碼存不進來。tests/test_config_pages.py 會拿碼表核對；
// 沒列出的輸入法（例如沒有碼表檔的嘸蝦米）只要求可見的 ASCII 字元。
var extendTableCodeKeys = {
    "chearray": "\"',-./0123456789;=[]_abcdefghijklmnopqrstuvwxyz{}",
    "checj": "!\"$%&'()*+,-./:;<=>?@[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~",
    "chedayi": "',-./0123456789;=[\\]`abcdefghijklmnopqrstuvwxyz",
    "cheez": "!\"#$&'()*+,-./0123456789:;<=>?[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~",
    "chephonetic": ",-./0123456789;abcdefghijklmnopqrstuvwxyz",
    "chepinyin": "12345abcdefghijklmnopqrstuvwxyz",
    "chesimplex": "abcdefghijklmnopqrstuvwxyz"
};

// 與後端的 safeSplit() 相同：有半形空白就從第一個空白切開，否則從第一個 Tab 切開。
// 沒有分隔時回傳 null。
function splitDataLine(line) {
    var at = line.indexOf(" ");
    if (at < 0) {
        at = line.indexOf("\t");
    }
    if (at < 0) {
        return null;
    }
    return [line.substring(0, at).trim(), line.substring(at + 1).trim()];
}

// 結合用字元（Unicode 類別 Mn、Mc、Me，含鍵帽 U+20E3）。不支援 \p{} 的舊瀏覽器
// 直接寫在正規式字面值裡會讓整個檔案語法錯誤、存檔全壞，所以用 RegExp 建立，
// 失敗時退回常見的結合用字元區段
var combiningMarkPattern = (function() {
    try {
        return new RegExp("^\\p{M}$", "u");
    } catch (e) {
        return /^[\u0300-\u036F\u1AB0-\u1AFF\u1DC0-\u1DFF\u20D0-\u20FF\uFE20-\uFE2F]$/;
    }
}());

function isSymbolExtender(ch) {
    var cp = ch.codePointAt(0);
    return (cp >= 0xFE00 && cp <= 0xFE0F)           // 變體選擇符（VS16 讓前一字顯示成彩色 emoji）
        || (cp >= 0xE0100 && cp <= 0xE01EF)         // 變體選擇符補充
        || (cp >= 0x1F3FB && cp <= 0x1F3FF)         // 膚色
        || (cp >= 0xE0020 && cp <= 0xE007F)         // 標籤字元（英格蘭等地區旗）
        || combiningMarkPattern.test(ch);
}

function isRegionalIndicator(ch) {
    var cp = ch.codePointAt(0);
    return cp >= 0x1F1E6 && cp <= 0x1F1FF;
}

// 與後端 cinbase/textclusters.py 的 symbolClusters() 相同：把文字切成一個個「符號」，
// 變體選擇符、膚色、ZWJ 連接、鍵帽、國旗與結合用字元都併入前一個符號。後端讀
// 符號檔就是這樣切的，所以字數要以它計算：逐碼位算時 ❤️（❤ + VS16）、🇹🇼、👍🏻
// 都是兩個字元，逐 UTF-16 單位算時連 😀 和 Ext-B 字也是兩個。
// tests/test_config_pages.py 會拿兩邊的結果核對。
function symbolClusters(text) {
    var clusters = [];
    var joinNext = false;
    var chars = Array.from(text);
    for (var i = 0; i < chars.length; i++) {
        var ch = chars[i];
        var last = clusters.length - 1;
        if (last >= 0 && (joinNext || ch === "\u200D" || isSymbolExtender(ch))) {
            clusters[last] += ch;
            joinNext = ch === "\u200D";             // ZWJ 之後那個字也屬於同一個符號
        } else if (last >= 0 && isRegionalIndicator(ch) && Array.from(clusters[last]).length === 1
                   && isRegionalIndicator(clusters[last])) {
            clusters[last] += ch;                   // 兩個區域指示符組成一面國旗
            joinNext = false;
        } else {
            clusters.push(ch);
            joinNext = false;
        }
    }
    return clusters;
}

// 簡易符號（swkb.dat）：「英文字母 空格 符號」，Shift+該字母輸出符號
function easySymbolLineError(line) {
    var parts = splitDataLine(line);
    if (!parts || !/^[A-Za-z]$/.test(parts[0]) || !parts[1] || symbolClusters(parts[1]).length > 10) {
        return "請使用「英文字母 + 空格 + 符號」的格式，符號最多 10 個字。";
    }
    return null;
}

// 「分類名稱=內容」，或一行只放一個符號（放在最上層選單）
function namedListLineError(line) {
    // 以符號計算：一行只放一個 Ext-B 字或 ❤️、🇹🇼 這類由多個碼位組成的表情符號也算一個
    if (line.indexOf("=") < 0 && symbolClusters(line).length > 1) {
        return "單行不能超過一個字元，或是沒有 = 符號區隔。";
    }
    return null;
}

// 擴展碼表（extendtable.dat）：「編碼 空格 字詞」，也接受 Tab，字詞長度不限
function extendTableLineError(line, imeName) {
    var parts = splitDataLine(line);
    if (!parts) {
        return "請使用「編碼 + 空格 + 字詞」的格式。";
    }
    var keys = extendTableCodeKeys.hasOwnProperty(imeName) ? extendTableCodeKeys[imeName] : null;
    var chars = Array.from(parts[0].toLowerCase());
    for (var i = 0; i < chars.length; i++) {
        var ch = chars[i];
        if (keys !== null ? keys.indexOf(ch) < 0 : !/^[!-~]$/.test(ch)) {
            return "編碼「" + parts[0] + "」裡的「" + (ch === "\t" ? "Tab" : ch) + "」不是這個輸入法的字根鍵。";
        }
    }
    return null;
}

// 找出第一行格式錯誤：回傳 { line: 行索引（從 0 起）, text: 該行原文, reason: 說明 }，
// 都正確時回傳 null。type："1" 簡易符號、"2" 名稱=內容、"3" 擴展碼表；
// imeName 是輸入法資料夾名稱（擴展碼表依它決定可用的字根鍵）。
function findDataFormatError(data, type, imeName) {
    var lines = String(data || "").split("\n");
    for (var i = 0; i < lines.length; i++) {
        // 後端讀檔時去掉 UTF-8 BOM 與行首行尾空白，並略過空行
        var line = lines[i].replace(/^\uFEFF/, "").trim();
        if (!line) {
            continue;
        }
        var reason = null;
        switch (type) {
            case "1":
                reason = easySymbolLineError(line);
                break;
            case "2":
                reason = namedListLineError(line);
                break;
            case "3":
                reason = extendTableLineError(line, imeName);
                break;
        }
        if (reason) {
            return { line: i, text: lines[i], reason: reason };
        }
    }
    return null;
}
