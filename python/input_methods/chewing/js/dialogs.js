// 設定頁與詞庫編輯頁共用的提示對話框：用瀏覽器內建的 <dialog>，不再需要 jQuery UI
// 或 sweetalert2。WimeDialog.alert({ title, message, icon, buttons, close })：
//   message  HTML 字串（含使用者資料時呼叫端先跳脫）
//   icon     "error" | "warning" | "success" | 其它（只決定標題前的符號）
//   buttons  { 按鈕文字: function (close) {...} }，省略時只有「確定」
//   close    對話框關閉後呼叫
(function (global) {
    var ICONS = { error: "❌", warning: "⚠️", success: "✔️" };

    function ensureDialog() {
        var dialog = document.getElementById("wime_alert");
        if (dialog) {
            return dialog;
        }
        dialog = document.createElement("dialog");
        dialog.id = "wime_alert";
        dialog.className = "wime-dialog";
        dialog.innerHTML =
            '<div class="wime-dialog-title"></div>' +
            '<div class="wime-dialog-body"></div>' +
            '<div class="wime-dialog-buttons"></div>';
        document.body.appendChild(dialog);
        return dialog;
    }

    function alertDialog(options) {
        var dialog = ensureDialog();
        var title = dialog.querySelector(".wime-dialog-title");
        var body = dialog.querySelector(".wime-dialog-body");
        var bar = dialog.querySelector(".wime-dialog-buttons");
        var icon = ICONS[options.icon] || "📘";

        title.textContent = icon + " " + (options.title || "");
        body.innerHTML = options.message || "";
        bar.innerHTML = "";

        var closed = false;
        function close() {
            if (closed) {
                return;
            }
            closed = true;
            if (dialog.open) {
                dialog.close();
            }
            if (typeof options.close === "function") {
                options.close();
            }
        }

        var buttons = options.buttons || { "確定": function (done) { done(); } };
        var first = null;
        Object.keys(buttons).forEach(function (label) {
            var button = document.createElement("button");
            button.type = "button";
            button.className = "wime-dialog-button";
            button.textContent = label;
            button.addEventListener("click", function () {
                buttons[label](close);
            });
            bar.appendChild(button);
            first = first || button;
        });

        // Esc 或點背景關閉時也要呼叫 close 回呼（例如把焦點放回輸入欄）
        dialog.oncancel = function (event) {
            event.preventDefault();
            close();
        };
        dialog.onclose = function () {
            close();
        };
        if (!dialog.open) {
            dialog.showModal();
        }
        if (first) {
            first.focus();
        }
        return close;
    }

    global.WimeDialog = { alert: alertDialog };
})(typeof window !== "undefined" ? window : this);
