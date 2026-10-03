// 此輸入法模組的資料夾名稱
var imeFolderName = "chedayi"

// 此輸入法模組使用的碼表
var selCins=[
    "泰瑞大易四碼",
    "大易四碼",
    "大易三碼"
];

// 此輸入法模組使用的鍵盤類型
var keyboardNames = [];

// 此輸入法模組在特定碼表須停用的設定項目 (從 0 開始, 100 之後代表全部碼表)
// 第三項（可省略）是停用的原因，會取代該項目的說明文字
var disableConfigItem = {
    2: ["homophoneQuery", false, "大易三碼的「`」是字根「巷」，不能用來查同音字。"],
    101: ["switchPageWithSpace", false],
    102: ["selWildcardType", null]
};


// 以下無須修改
// ==============================================================================================

includeScriptFile("js/config.js")

function includeScriptFile(filename)
{
    var head = document.getElementsByTagName('head')[0];

    script = document.createElement('script');
    script.src = filename;
    script.type = 'text/javascript';

    head.appendChild(script)
}
