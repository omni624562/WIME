// 詞彙和注音來自使用者詞庫 (可能是匯入的檔案)，放進 HTML 之前一定要跳脫，
// 否則詞彙裡的 <img onerror=...> 會在設定工具的頁面裡執行
function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, function(c) {
        return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c];
    });
}

// 讀回表格裡的詞彙和注音 (用 attr 而不是 data()：jQuery 的 data() 會把 "123" 轉成數字)
function phraseOf(item) {
    return $(item).attr("data-phrase");
}

function bopomofoOf(item) {
    return $(item).attr("data-bopomofo");
}

function serverErrorText(xhr, action) {
    let status = xhr ? xhr.status : 0;
    if (status === 403) {
        return action + "失敗：設定工具的工作階段已失效，請關閉此頁再重新開啟詞庫編輯器。";
    }
    if (!status) {
        return action + "失敗：無法連線到設定工具（可能已關閉），請關閉此頁再重新開啟詞庫編輯器。";
    }
    if (status === 503) {
        return action + "失敗：無法開啟使用者詞庫（可能被其他程式使用中或已損毀）。";
    }
    return action + "失敗（HTTP " + status + "）。";
}

// 漢字 (含擴充 A、相容表意文字與擴充 B 之後的字)
function isHanCodePoint(cp) {
    return (cp >= 0x3400 && cp <= 0x4DBF) || (cp >= 0x4E00 && cp <= 0x9FFF) ||
        (cp >= 0xF900 && cp <= 0xFAFF) || (cp >= 0x20000 && cp <= 0x3134F);
}

// Load user phrases
function loadUserPhrases() {
    $("#add_dialog").dialog("close");
    $("#delete_count").html("");

    // Show loading overlay
    $.LoadingOverlay("show", {
        background: "rgba(80, 80, 80, 0.8)",
        fade: [200, 500],
        text: "載入詞彙中，請稍候..."
    });

    // Get user_phrases
    $.get("/user_phrases", function(data, status) {
        if (data.data != undefined) {
            let user_phrase_html = data.data.map(function(user_phrase) {
                let phrase = escapeHtml(user_phrase.phrase);
                let bopomofo = escapeHtml(user_phrase.bopomofo);
                return `<tr>
                <td><input type="checkbox" data-phrase="${phrase}" data-bopomofo="${bopomofo}">${phrase}</td>
                <td>${bopomofo}</td>
                </tr>`;
            }).join("");

            // For performace reason, use DOM API to render content
            document.querySelector("#table_content").innerHTML = user_phrase_html;
            $("#phrase_count").html(`共&nbsp;${data.data.length}&nbsp;個詞彙`);
        }

        // Hide loading overlay
        $.LoadingOverlay("hide", true);

        // Register click table row to select phrase
        $("#table_content").on("click", function(e) {
            let targetObj = $(e.target);

            // Register click table row to select phrase
            if (targetObj.is("td")) {
                targetObj.parent().find("input[type=checkbox]")
                    .prop("checked", !targetObj.parent().find("input[type=checkbox]").prop("checked"));
                targetObj.parent().toggleClass("phrase_selected");
            }

            // Checkbox hightlight phrase row
            if (targetObj.is("input[type=checkbox]")) {
                targetObj.parent().parent().toggleClass("phrase_selected");
            }

            // Update delete phrases count
            if ($("#table_content input[type=checkbox]:checked").length !== 0) {
                $("#delete_count").html(`（${$("#table_content input[type=checkbox]:checked").length}）`);
            } else {
                $("#delete_count").html("");
            }
        });

        // Register click to select all phrases
        $("input[type=checkbox][name='select_all']").prop("checked", false);
        $("input[type=checkbox][name='select_all']").on("click", function() {
            if ($(this).prop("checked")) {
                $("#table_content input[type=checkbox]").prop("checked", true);
                $("#table_content tr").addClass("phrase_selected");
                $("#delete_count").html(`（${$("#table_content input[type=checkbox]:checked").length}）`);
            } else {
                $("#table_content input[type=checkbox]").prop("checked", false);
                $("#table_content tr").removeClass("phrase_selected");
                $("#delete_count").html("");
            }
        });
    }, "json").fail(function(xhr) {
        // 以前沒有處理錯誤，「載入詞彙中」的遮罩永遠不會消失
        $.LoadingOverlay("hide", true);
        jQueryDialogAlert({
            message: escapeHtml(serverErrorText(xhr, "載入詞彙")),
            icon: "error"
        });
    });
}

// called when the OK button of the "add phrase" dialog is clicked
function onAddPhrase() {
    let phrase = $("#phrase_input").val().trim();
    let bopomofo = $("#bopomofo_input").val().replaceAll("_", " ").trim();

    // Check phrase not empty
    if (phrase.length < 1) {
        jQueryDialogAlert({
            message: "請輸入詞彙",
            icon: "error",
            close: () => {
                $("#phrase_input").select();
            }
        });
        return;
    }

    // Check phrase is chinese (逐個字碼檢查：擴充 B 之後的字在 JavaScript 裡佔兩個 UTF-16 單位)
    let phrase_chars = Array.from(phrase);
    let offset = 0;
    for (let i = 0; i < phrase_chars.length; i++) {
        let start = offset;
        let end = offset + phrase_chars[i].length;
        offset = end;
        if (!isHanCodePoint(phrase_chars[i].codePointAt(0))) {
            jQueryDialogAlert({
                message: "詞彙錯誤，有不是中文的字",
                icon: "error",
                close: () => {
                    $("#phrase_input").select();
                    $("#phrase_input")[0].setSelectionRange(start, end);
                }
            });
            return;
        }
    }

    // Check bopomofo not empty
    if (bopomofo.length < 1) {
        jQueryDialogAlert({
            message: "請輸入注音",
            icon: "error",
            close: () => {
                $("#bopomofo_input").select()
            }
        });
        return;
    }

    // Check bopomofo is correct
    let bopomofo_check_string = "ㄅㄆㄇㄈㄉㄊㄋㄌㄍㄎㄏㄐㄑㄒㄓㄔㄕㄖㄗㄘㄙㄧㄨㄩㄚㄛㄜㄝㄞㄟㄠㄡㄢㄣㄤㄥㄦ ˊˇˋ˙";
    for (let i = 0; i < bopomofo.length; i++) {
        if (bopomofo_check_string.indexOf(bopomofo.substring(i, i + 1)) == -1) {
            jQueryDialogAlert({
                message: "注音符號錯誤，請輸入正確的注音",
                icon: "error",
                close: () => {
                    $("#bopomofo_input").select();
                    $("#bopomofo_input")[0].setSelectionRange(i, i + 1);
                }
            });
            return;
        }
    }

    // Check bopomofo and phrase count are equal
    let bopomofo_array = bopomofo.split(" ");
    if (bopomofo_array.length != phrase_chars.length && phrase_chars.length > 1 && bopomofo.length > 1) {
        jQueryDialogAlert({
            message: "注音符號跟詞彙字數不符",
            icon: "error",
            close: () => {
                $("#phrase_input").select();
            }
        });
        return;
    }

    // Check phrase not exist (同一個詞可以有不同的讀音，所以詞彙和注音都要相同才算重複)
    let phrase_repeated;
    let phrase_repeated_index;
    $("#table_content input[type=checkbox]").each(function(idx, item) {
        if (phrase === phraseOf(item) && bopomofo === bopomofoOf(item)) {
            phrase_repeated = true;
            phrase_repeated_index = idx;
            return false;
        }
    });

    if (phrase_repeated == true) {
        let phrase_repeated_item = $(`#table_content input[type=checkbox]:eq(${phrase_repeated_index})`);
        $("html, body").animate({
            scrollTop: phrase_repeated_item.offset().top - 200
        }, 200);
        phrase_repeated_item.parent().effect("highlight", {
            color: "#f2f207"
        }, 5000);
        jQueryDialogAlert({
            message: "詞彙已經存在，請重新輸入",
            icon: "error",
            close: () => {
                $("#phrase_input").select();
            }
        });
        return;
    }

    // Execute add phrase
    $.ajax({
        url: "/user_phrases",
        method: "POST",
        contentType: "application/json",
        data: JSON.stringify({
            add: [{
                phrase: phrase,
                bopomofo: bopomofo
            }]
        }),
        dataType: "json",
        complete: function(response) {
            if (!response.responseJSON) {  // HTTP 錯誤或連不到設定工具
                jQueryDialogAlert({
                    message: escapeHtml(serverErrorText(response, "新增詞彙")),
                    icon: "error"
                });
            } else if (response.responseJSON.result == 0) {
                jQueryDialogAlert({
                    message: "新增失敗，請檢查詞彙跟注音格式是否正確",
                    icon: "error"
                });
            } else {
                jQueryDialogAlert({
                    message: "新增詞彙成功！",
                    icon: "success",
                    close: () => {
                        location.reload();
                    }
                });
            }
        }
    });
}

// Execute remove phrase
function onRemovePhrase() {
    if ($("#table_content input[type=checkbox]:checked").length === 0) {
        jQueryDialogAlert({
            message: "請先選擇要刪除的詞彙",
            icon: "error"
        });
    } else {
        let phrases = [];
        let confirm_text;

        if ($("#table_content input[type=checkbox]:checked").length === 0) {
            return;
        }

        confirm_text = `確定刪除以下 ${$("#table_content input[type=checkbox]:checked").length} 個詞彙？此動作無法復原<br><ul>`;
        $("#table_content input[type=checkbox]:checked").each(function(phrase_index, item) {
            if (phrase_index < 10) {
                confirm_text += `<li>${escapeHtml(phraseOf(item))}</li>`;
            } else if (phrase_index === 10) {
                confirm_text += "<li>………（以下省略）</li>";
            }
            phrases.push({
                phrase: phraseOf(item), // 詞彙
                bopomofo: bopomofoOf(item) // 注音
            });
        });
        confirm_text += "</ul>";

        jQueryDialogAlert({
            title: "確認刪除詞彙",
            message: `<div style="text-align: left;">${confirm_text}</div>`,
            icon: "warning",
            buttons: {
                "繼續": function() {
                    $.ajax({
                        url: "/user_phrases",
                        method: "POST",
                        contentType: "application/json",
                        data: JSON.stringify({
                            remove: phrases
                        }),
                        dataType: "json",
                        success: function(data) {
                            // 以前不看結果，刪除失敗也顯示成功
                            let ok = data && data.result != 0;
                            jQueryDialogAlert({
                                message: ok ? "刪除詞彙成功！" : "有些詞彙刪除失敗，請重新載入後再試一次",
                                icon: ok ? "success" : "error",
                                close: () => {
                                    location.reload();
                                }
                            });
                        },
                        error: function(xhr) {
                            jQueryDialogAlert({
                                message: escapeHtml(serverErrorText(xhr, "刪除詞彙")),
                                icon: "error"
                            });
                        }
                    });
                },
                "取消": function() {
                    $(this).dialog('close');
                }
            }
        });
    }
}

// Execute export user phrases
function onExportPhrase() {
    window.location.href = "/user_phrase_file";
}

// Execute import user phrases
// AJAX file upload
function onImportPhrase() {
    jQueryDialogAlert({
        title: "確認匯入詞彙",
        message: "警告！匯入詞庫會<b>清除現有詞庫</b>，以匯入的詞庫取代，要繼續嗎？",
        icon: "warning",
        buttons: {
            "繼續": function() {
                $("#import_user_phrase").on("change", function() {
                    if (this.files[0].name.split(".").pop() === "sqlite3") {
                        $("#import_user_phrase_form").submit();
                    } else {
                        jQueryDialogAlert({
                            message: "副檔名錯誤！只允許 .sqlite3 檔案上傳！",
                            icon: "error"
                        });
                    }
                });
                $("#import_user_phrase").click();
            },
            "取消": function() {
                $(this).dialog('close');
            }
        }
    });
}

function jQueryDialogAlert(options) {
    let title = (options.title !== undefined) ? options.title : "";
    switch (options.icon) {
        case "error":
            options.title = `❌ ${title}`;
            break;
        case "warning":
            options.title = `⚠️ ${title}`;
            break;
        case "success":
            options.title = `✔️ ${title}`;
            break;
        default:
            options.title = `📘 ${title}`;
            break;
    }
    $("#jquery_alert").html(options.message).dialog({
        show: {
            effect: "scale",
            duration: 300
        },
        hide: {
            effect: "scale",
            duration: 300
        },
        width: 600,
        resizable: false,
        modal: true,
        title: title,
        buttons: {
            'Ok': function() {
                $(this).dialog('close');
            }
        },
        ...options
    });
}

// jQuery ready
$(function() {
    // workaround the same origin policy of IE.
    // http://stackoverflow.com/questions/7852225/is-it-safe-to-use-support-cors-true-in-jquery
    $.support.cors = true;

    // setup UI
    $("#user_phrase_buttons").controlgroup({
        direction: "vertical"
    });

    // add phrase dialog
    $("#add_dialog").dialog({
        show: {
            effect: "scale",
            duration: 400
        },
        hide: {
            effect: "scale",
            duration: 400
        },
        autoOpen: false,
        resizable: false,
        modal: true,
        dialogClass: "fixed_dialog",
        width: 500,
        buttons: [{
            text: "確定",
            click: onAddPhrase
        }, {
            text: "取消",
            click: function() {
                $(this).dialog("close");
            }
        }]
    });

    $("#add").on("click", function() {
        $("#phrase_input").val("");
        $("#bopomofo_input").val("");
        $("#add_dialog").dialog("open");
    });
    $("#remove").on("click", onRemovePhrase);
    $("#reload").on("click", function() {
        location.reload();
    });
    $("#import").on("click", onImportPhrase);
    $("#export").on("click", onExportPhrase);

    // Change input to bopomofo
    $("#bopomofo_input").on("input", function(event) {
        let keycode_to_bopomofo = {
            49: "ㄅ",
            81: "ㄆ",
            113: "ㄆ",
            65: "ㄇ",
            97: "ㄇ",
            90: "ㄈ",
            122: "ㄈ",
            50: "ㄉ",
            87: "ㄊ",
            119: "ㄊ",
            83: "ㄋ",
            115: "ㄋ",
            88: "ㄌ",
            120: "ㄌ",
            69: "ㄍ",
            101: "ㄍ",
            68: "ㄎ",
            100: "ㄎ",
            67: "ㄏ",
            99: "ㄏ",
            82: "ㄐ",
            114: "ㄐ",
            70: "ㄑ",
            102: "ㄑ",
            86: "ㄒ",
            118: "ㄒ",
            53: "ㄓ",
            84: "ㄔ",
            116: "ㄔ",
            71: "ㄕ",
            103: "ㄕ",
            66: "ㄖ",
            98: "ㄖ",
            89: "ㄗ",
            121: "ㄗ",
            72: "ㄘ",
            104: "ㄘ",
            78: "ㄙ",
            110: "ㄙ",
            85: "ㄧ",
            117: "ㄧ",
            74: "ㄨ",
            106: "ㄨ",
            77: "ㄩ",
            109: "ㄩ",
            56: "ㄚ",
            73: "ㄛ",
            105: "ㄛ",
            75: "ㄜ",
            107: "ㄜ",
            44: "ㄝ",
            57: "ㄞ",
            79: "ㄟ",
            111: "ㄟ",
            76: "ㄠ",
            108: "ㄠ",
            46: "ㄡ",
            48: "ㄢ",
            80: "ㄣ",
            112: "ㄣ",
            59: "ㄤ",
            191: "ㄥ",
            47: "ㄥ",
            45: "ㄦ",
            54: "ˊ",
            51: "ˇ",
            52: "ˋ",
            55: "˙",
            32: "_"
        };
        let bopomofo_input = $("#bopomofo_input").val();
        let bopomofo_string = "";
        for (let i = 0; i < bopomofo_input.length; i++) {
            if (keycode_to_bopomofo[bopomofo_input.charCodeAt(i)] != undefined) {
                bopomofo_string += keycode_to_bopomofo[bopomofo_input.charCodeAt(i)];
            } else {
                bopomofo_string += bopomofo_input.substring(i, i + 1);
            }
        }
        $("#bopomofo_input").val(bopomofo_string);
    });

    loadUserPhrases();

    // keep the server alive every 20 second
    window.setInterval(function() {
        $.ajax({
            url: "/keep_alive",
            cache: false // needs to turn off cache. otherwise the server will be requested only once.
        });
    }, 20 * 1000);
});
