$(function () {
    var chewingConfig = {},
        symbolsChanged = false,
        swkbChanged = false,
        DEBUG = false,
        CONFIG_URL = "/config",
        VERSION_URL = "/version.txt",
        KEEP_ALIVE_URL = "/keep_alive";

    if (DEBUG) {
        // load data from text file for testing or developing
        CONFIG_URL = "debug" + CONFIG_URL;
        VERSION_URL = "debug" + VERSION_URL;
        KEEP_ALIVE_URL = "debug" + KEEP_ALIVE_URL;
    }

    function loadConfig() {
        $.get(
            CONFIG_URL,
            function (data, status) {
                chewingConfig = data.config;
                applyCandidateDefaults();
                $("#symbols").val(data.symbols);
                $("#ez_symbols").val(data.swkb);
                initializeUI();
            },
            "json"
        );
    }

    function applyCandidateDefaults() {
        if (typeof chewingConfig.candidateModernStyle === "undefined") {
            chewingConfig.candidateModernStyle = true;
        }
        if (typeof chewingConfig.candidateStableWidth === "undefined") {
            chewingConfig.candidateStableWidth = true;
        }
        if (typeof chewingConfig.candidateMinWidth === "undefined" || chewingConfig.candidateMinWidth < 160) {
            chewingConfig.candidateMinWidth = 286;
        }
        if (typeof chewingConfig.candidateWrapToMaxWidth === "undefined") {
            chewingConfig.candidateWrapToMaxWidth = true;
        }
        if (typeof chewingConfig.candidateMaxWidth === "undefined" || chewingConfig.candidateMaxWidth < 220) {
            chewingConfig.candidateMaxWidth = 300;
        }
        if (typeof chewingConfig.candidateTheme === "undefined") {
            chewingConfig.candidateTheme = "Night Comfort";
        }
        if (typeof chewingConfig.candidatePerRow === "undefined") {
            chewingConfig.candidatePerRow = 6;
        }
        if (typeof chewingConfig.candidateEdgeAvoidance === "undefined") {
            chewingConfig.candidateEdgeAvoidance = true;
        }
    }

    let candidateThemeNames = [
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
        "Sepia Dim",
    ];

    let candidateThemePalette = {
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
        "Sepia Dim": ["#28251f", "#5d564a", "#403a31", "#ebe2d3", "#b9ad9a", "#dfc58e", "#6d6547", "#958a63", "#f8efd9", "#c7b79e"],
    };

    function getCandidatePreviewSample() {
        return {
            name: "新酷音",
            root: "ㄅ",
            candidates: ["班", "般", "搬", "斑", "伴", "辦", "半", "板", "版", "頒"],
        };
    }

    function applyCandidatePreviewTheme(preview, theme, modern) {
        preview.css({
            "background-color": modern ? theme[0] : "#ffffff",
            "border-color": modern ? theme[1] : "#000000",
            "border-radius": modern ? "6px" : "0",
            color: modern ? theme[3] : "#000000",
        });
        preview.find(".candidate-preview-header").css("border-bottom-color", modern ? theme[2] : "#d0d0d0");
        preview.find(".candidate-preview-name, .candidate-preview-page").css("color", modern ? theme[4] : "#0000b4");
        preview.find(".candidate-preview-root").css("color", modern ? theme[5] : "#0000b4");
        preview.find(".candidate-preview-item span").css("color", modern ? theme[9] : "#0000ff");
        preview.find(".candidate-preview-item.active").css({
            "background-color": modern ? theme[6] : "#000000",
            "border-color": modern ? theme[7] : "#000000",
            "border-radius": modern ? "6px" : "0",
            color: modern ? theme[8] : "#ffffff",
        });
        preview.find(".candidate-preview-item.active span").css("color", modern ? theme[8] : "#ffffff");
    }

    function fillCandidatePreviewItems(preview, sample) {
        let count = Number.parseInt($("#candidatePerRow").val()) || 4;
        count = Math.max(1, Math.min(count, 10));
        let body = preview.find(".candidate-preview-body");
        body.empty();

        for (let i = 0; i < count; ++i) {
            let item = $("<span>").addClass("candidate-preview-item");
            if (i === 0) {
                item.addClass("active");
            }
            item.append($("<span>").text(String(i + 1).slice(-1)));
            item.append(document.createTextNode(sample.candidates[i % sample.candidates.length]));
            body.append(item);
        }
    }

    function candidatePreviewFontSize() {
        let fontSize = Number.parseInt($("#fontSize").val()) || 12;
        return Math.max(6, Math.min(fontSize, 48));
    }

    function createCandidatePreview(sample) {
        let preview = $("<div>").addClass("candidate-preview");
        let header = $("<div>").addClass("candidate-preview-header");
        header.append($("<span>").addClass("candidate-preview-name").text(sample.name));
        header.append($("<span>").addClass("candidate-preview-root").text(sample.root));
        header.append($("<span>").addClass("candidate-preview-page").text("1/1"));
        preview.append(header);
        preview.append($("<div>").addClass("candidate-preview-body"));
        fillCandidatePreviewItems(preview, sample);
        return preview;
    }

    function renderCandidateThemeGallery() {
        let grid = $("#candidateThemeGrid");
        if (!grid.length) {
            return;
        }

        let sample = getCandidatePreviewSample();
        grid.empty();
        for (let i = 0; i < candidateThemeNames.length; ++i) {
            let themeName = candidateThemeNames[i];
            let card = $("<button>").attr("type", "button").addClass("candidate-theme-card").data("theme", themeName);
            let header = $("<div>").addClass("candidate-theme-card-header");
            header.append($("<span>").addClass("candidate-theme-card-name").text(themeName));
            header.append($("<span>").addClass("candidate-theme-card-state"));
            card.append(header);
            card.append(createCandidatePreview(sample));
            grid.append(card);
        }
    }

    function updateCandidateThemeGallery() {
        let grid = $("#candidateThemeGrid");
        if (!grid.length) {
            return;
        }

        let selectedTheme = $("#candidateTheme").val() || "Night Comfort";
        let modern = $("#candidateModernStyle").prop("checked");
        let stableWidth = $("#candidateStableWidth").prop("checked");
        let wrapToMaxWidth = $("#candidateWrapToMaxWidth").prop("checked");
        let sample = getCandidatePreviewSample();
        $("#candidateMinWidth").prop("disabled", !stableWidth);
        $("#candidateMaxWidth").prop("disabled", !wrapToMaxWidth);
        $("#candidateThemeCurrent").text(selectedTheme);

        grid.find(".candidate-theme-card").each(function () {
            let card = $(this);
            let themeName = card.data("theme");
            let selected = themeName === selectedTheme;
            let preview = card.find(".candidate-preview");
            card.toggleClass("selected", selected);
            preview.toggleClass("wrap", wrapToMaxWidth);
            preview.css("font-size", `${candidatePreviewFontSize()}pt`);
            card.find(".candidate-theme-card-state").text(selected ? "已選" : "");
            preview.find(".candidate-preview-name").text(sample.name);
            preview.find(".candidate-preview-root").text(sample.root);
            fillCandidatePreviewItems(preview, sample);
            applyCandidatePreviewTheme(preview, candidateThemePalette[themeName] || candidateThemePalette["Night Comfort"], modern);
        });
    }

    function saveConfig(callbackFunc) {
        // Check easy symbols format
        let ez_symbols_array = $("#ez_symbols").val().split("\n");
        for (let i = 0; i < ez_symbols_array.length; i++) {
            if (!/^[A-Z][ ].{1,10}$/.test(ez_symbols_array[i])) {
                // Select error range
                $("#ez_symbols").select();
                let selectionStart = 0;
                for (let j = 0; j < i; j++) {
                    selectionStart += ez_symbols_array[j].length + 1;
                }
                $("#ez_symbols").prop("selectionStart", selectionStart);
                $("#ez_symbols").prop("selectionEnd", selectionStart + ez_symbols_array[i].length + 1);
                swal.fire(
                    "輸入錯誤",
                    `第 ${i} 行格式錯誤：<br><b>${ez_symbols_array[i]}</b><br>請使用「英文大寫 + 空格 + 字串」的格式，字串最多10個字元`,
                    "error"
                );
                return false;
            }
        }

        // Check symbols format
        let symbols_array = $("#symbols").val().split("\n");
        for (let i = 0; i < symbols_array.length; i++) {
            if (symbols_array[i].length > 1 && symbols_array[i].search("=") === -1) {
                // Select error range
                $("#symbols").select();
                let selectionStart = 1;
                for (let j = 0; j < i; j++) {
                    selectionStart += symbols_array[j].length;
                }
                $("#symbols").prop("selectionStart", selectionStart);
                $("#symbols").prop("selectionEnd", selectionStart + symbols_array[i].length);
                swal.fire(
                    "輸入錯誤",
                    `特殊符號設定第 ${i + 1} 行格式錯誤：<br><b>${symbols_array[i]}</b><br>單行不能超過一個字元，或是沒有 = 符號區隔`,
                    "error"
                );
                return false;
            }
        }

        let data = {
            config: chewingConfig,
        };

        // Append "\n" on symbols end prevent error
        if (symbolsChanged) {
            if ($("#symbols").val().slice(-1) !== "\n") {
                $("#symbols").val(`${$("#symbols").val()}\n`);
            }
            data.symbols = $("#symbols").val();
        }

        if (swkbChanged) {
            data.swkb = $("#ez_symbols").val();
        }

        $.ajax({
            url: CONFIG_URL,
            method: "POST",
            success: callbackFunc,
            contentType: "application/json",
            data: JSON.stringify(data),
            dataType: "json",
        });
    }

    // Update chewingConfig object with the value set by the user
    function updateConfig() {
        // Preserve settings that are not shown on the current page.
        chewingConfig = $.extend(true, {}, chewingConfig);

        // Get values from checkboxes, text, hidden and radio
        $(".container input").each(function (index, inputItem) {
            switch (inputItem.type) {
                case "checkbox":
                    chewingConfig[inputItem.name] = inputItem.checked;
                    break;
                case "text":
                case "hidden":
                case "number":
                    chewingConfig[inputItem.name] = Number.parseInt(inputItem.value);
                    break;
                case "radio":
                    if (inputItem.checked === true) {
                        chewingConfig[inputItem.name] = Number.parseInt(inputItem.value);
                    }
                    break;
            }
        });

        // Get values from select
        $(".container select").each(function (index, selectItem) {
            if (selectItem.value) {
                if ($(selectItem).data("value-type") === "string") {
                    chewingConfig[selectItem.name] = selectItem.value;
                }
                else {
                    chewingConfig[selectItem.name] = Number.parseInt(selectItem.value);
                }
            }
        });

        if (chewingConfig.candidateTheme) {
            chewingConfig.candidateColors = {};
        }
    }

    // Initialize UI
    function initializeUI() {
        // Setup checkbox and text values
        $(".container input").each(function () {
            switch ($(this).attr("type")) {
                case "checkbox":
                    $(this).prop("checked", chewingConfig[$(this).attr("id")]);
                    break;
                case "text":
                case "number":
                    $(this).val(chewingConfig[$(this).attr("id")]);
                    break;
            }
        });

        // Setup select options and values
        let selectOptions = {
            switchLangWithWhichShift: ["左右兩邊都使用", "僅使用左 Shift", "僅使用右 Shift"],
            upDownAction: ["移動游標選字", "在選字時翻頁"],
            leftRightAction: ["移動游標選字（循環）", "在選字時翻頁"],
            spaceKeyAction: {
                1: "叫出選字視窗",
                0: "輸出空格",
            },
            spaceKeyCandidatesAction: {
                1: "移動游標（循環）",
                0: "翻頁",
            },
            selKeyType: ["1234567890", "asdfghjkl;", "asdfzxcv89", "asdfjkl789", "aoeuhtn789", "1234qweras"],
            addPhraseForward: ["後方的詞", "前方的詞"],
            candidateTheme: {
                "Night Comfort": "Night Comfort",
                "Soft Focus": "Soft Focus",
                "Warm Gray": "Warm Gray",
                "Graphite": "Graphite",
                "Slate Teal": "Slate Teal",
                "Olive": "Olive",
                "Plum": "Plum",
                "Amber": "Amber",
                "Light": "Light",
                "Paper": "Paper",
                "Mist Light": "Mist Light",
                "Sepia Dim": "Sepia Dim",
            },
        };

        $.each(selectOptions, function (id, options) {
            $.each(options, function (value, optionName) {
                $("#" + id).append('<option value="' + value + '">' + optionName + "</option>");
                if (value == chewingConfig[id]) {
                    $(`#${id} option:last-child`).prop("selected", true);
                }
            });
        });

        // Setup switchLangWithWhichShift's default disabled property
        $("#switchLangWithWhichShift").prop("disabled", !chewingConfig["switchLangWithShift"]);

        // Bind Bootstrap
        $(".container select").not(".candidate-theme-select").selectpicker();
        $('[data-toggle="popover"]').popover();

        // When switchLangWithShift's value changed, update switchLangWithWhichShift's disabled property
        $("#switchLangWithShift").on("click", function () {
            $("#switchLangWithWhichShift").prop("disabled", !this.checked).selectpicker("refresh");
        });

        // Bind shift action event
        $("#switchLangWithShift").on("click", function () {
            if (this.checked) {
                $("#shiftMoveCursor").prop("checked", false);
            }
        });
        $("#shiftMoveCursor").on("click", function () {
            if (this.checked) {
                $("#switchLangWithShift").prop("checked", false);
                $("#switchLangWithWhichShift").prop("disabled", true).selectpicker("refresh");
            }
        });

        // Setup select phrase example & Bind updateSelExample event
        updateSelExample();
        $("#ui_tab input, #ui_tab select").on("change keyup", updateSelExample);
        renderCandidateThemeGallery();
        updateCandidateThemeGallery();
        $(".candidate_window_settings input, .candidate_window_settings select").on("change keyup", updateCandidateThemeGallery);
        $("#candidateThemeGrid").on("click", ".candidate-theme-card", function () {
            $("#candidateTheme").val($(this).data("theme"));
            updateCandidateThemeGallery();
        });

        // Setup keybord page
        let keyboardNames = [
            ["預設", "default-chewing"],
            ["許氏鍵盤", "hsu"],
            ["IBM", "ibm"],
            ["精業", "jingye"],
            ["倚天 41 鍵", "et41"],
            ["倚天 26 鍵", "et26"],
            ["DVORAK", "dvorak-chewing"],
            ["DVORAK 許氏鍵盤", "dvorak-hsu"],
            ["大千 26 鍵", "dacian26"],
            ["漢語拼音", "pinyin"],
            ["台灣華語羅馬拼音", "pinyin"],
            ["注音二式", "pinyin"],
            ["CARPALX", "carpalx"],
        ];

        let item = '<img id="keyboard_layouts" src="images\\keyborad_layouts\\pinyin.png" alt="pinyin">';

        for (let i = 0; i < keyboardNames.length; ++i) {
            let id = `kb${i}`;
            let name = keyboardNames[i][0];
            let layout = keyboardNames[i][1];
            item +=
                '<div class="custom-control custom-radio">' +
                '<input class="custom-control-input" type="radio" id="' +
                id +
                '" name="keyboardLayout" value="' +
                i +
                '" data-layout="' +
                layout +
                '">' +
                '<label class="custom-control-label" for="' +
                id +
                '">' +
                name +
                "</label><br>" +
                "</div>";
        }
        $("#keyboard_tab").html(item);

        // Checked keyboard layout radio
        let checkedKetboardLayoutRadio = $(`#kb${chewingConfig.keyboardLayout}`);
        checkedKetboardLayoutRadio.prop("checked", true);
        $("#keyboard_layouts").prop("src", `images/keyborad_layouts/${checkedKetboardLayoutRadio.data("layout")}.png`);
        $("#keyboard_layouts").prop("alt", checkedKetboardLayoutRadio.data("layout"));

        // Bind change keyboard_layouts event
        $("#keyboard_tab input:radio").on("click", function () {
            let layout_file_name = $(this).data("layout");
            $("#keyboard_layouts").fadeOut(200, function () {
                $("#keyboard_layouts").prop("src", `images/keyborad_layouts/${layout_file_name}.png`);
                $("#keyboard_layouts").prop("alt", layout_file_name);
            });

            $("#keyboard_layouts").fadeIn(200);
        });
    }

    // Use for select phrase example
    function updateSelExample() {
        let example = ["選", "字", "視", "窗", "大", "小", "範", "例"];
        let selectItems = $("#selKeyType option").eq($("#selKeyType").val()).html();
        let html = "";

        for (let number = 0, i = 0, row = 0; number < $("#candPerPage").val(); number++, i++, row++) {
            if (example[i] == null) {
                i = 0;
            }

            if (row == $("#candPerRow").val()) {
                row = 0;
                html += "<br>";
            }

            html += `<span>${selectItems.substr(number, 1)}.</span>${example[i]}`;
        }

        $("#selExample").html(html);
        $("#selExample").css("font-size", `${$("#fontSize").val()}pt`);
    }

    // workaround the same origin policy of IE.
    // http://stackoverflow.com/questions/7852225/is-it-safe-to-use-support-cors-true-in-jquery
    $.support.cors = true;

    // Show PIME version number
    $("#version").load(VERSION_URL);

    // Setup UI
    $("#symbols").on("change", function () {
        symbolsChanged = true;
    });

    $("#ez_symbols").on("change", function () {
        swkbChanged = true;
    });

    // OK button
    $("#ok").on("click", function () {
        updateConfig(); // update the config based on the state of UI elements
        saveConfig(function () {
            swal.fire("好耶！", "設定成功儲存！", "success");
        });
        return false;
    });

    // Load configurations and update the UI accordingly
    loadConfig();

    // Keep the server alive every 20 second
    setInterval(function () {
        $.ajax({
            url: KEEP_ALIVE_URL + "?" + Date.now(),
        });
    }, 20 * 1000);

    // Bind test input auto select
    $("#test_input").on("shown.bs.modal", function () {
        $("#test_input_text").val("").select();
    });

    return false;
});
