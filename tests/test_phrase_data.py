"""The built-in phrase-suggestion dictionary (python/cinbase/data/phrase.json).

The 197 phrases below used to be hidden by the default exclusion list
(python/cinbase/data/excludephrase.dat, 170 lines) and were deleted from the
dictionary itself at the user's request (2026-09-29), so they are gone on every
computer the installer goes on, not only where the exclusion list is present.
This test keeps them from coming back if phrase.json is ever regenerated.
The same goes for the 119 China-related phrases in REMOVED_CHINA, deleted later
the same day.
"""

import json
import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
PHRASE_JSON = os.path.join(ROOT, "python", "cinbase", "data", "phrase.json")

# 首字=後續字,後續字 (same syntax as the exclusion list)
REMOVED = """
仰=韶文化
伍=子胥
伏=羲
信=息
傅=斯年
內=蒙
共=產,產主義
列=寧,寧主義
叔=本華
史=密斯,達林,特勞斯,迪威
司=馬光,馬遷
后=羿,稷
吳=鳳,佩孚
周=公
唐=山
喬=治,治華盛頓
夏=娃,桀
天=津
姜=子牙,太公
孔=子,夫子,孟
孟=子,姜女
季=辛吉
孫=子,悟空,子兵法
富=蘭克林
寧=夏
屈=原
屠=格涅夫
平=劇
康=有為
廈=門
張=三
彭=祖
徐=志摩,光啟
成=吉思汗
晏=子
普=通話
景=德鎮
杜=魯門,甫,威
林=語堂
柏=拉圖
柴=可夫斯基
桓=玄
梁=山伯,實秋,任公,啟超
歐=本海默
武=后,大郎,則天
江=浙,寧
海=南,南島
溥=儀
滿=洲,州國
潘=金蓮
狄=青,更斯
王=永慶,維,陽明,八蛋,貞治,昭君,荊公,充,安石,羲之
班=超,昭
甘=迺迪,地
畢=卡索,加索
白=痴,馬王子,雪公主,癡
社=會主義,會主義者
祝=英台
福=州,州市
秦=皇島,嶺,淮河
穆=罕默德
竇=憲
簡=體字
米=勒,開蘭基羅
紫=禁城
統=戰
網=絡
羅=蘭
老=子
舒=伯特
艾=森豪,略特
荊=軻
莊=子
莫=札特,扎特
華=南,東,夏,中,北
蒲=松齡
蕭=邦,薔,伯納
蘇=俄,州,維埃,哈托,東坡,維埃聯邦,曼殊,武,秦
詹=森,姆士,天佑
諸=葛,葛亮
谷=正綱
豐=臣秀吉
貝=爾,多芬
質=量
赫=魯雪夫,胥黎
邱=吉爾
郝=柏村
郭=婉容,子儀
都=卜勒
重=慶
關=公,羽
陶=淵明,朱公
雷=根
青=海
韋=伯
韓=信,愈,德爾,福瑞
頤=和園
顧=愷之
馬=偕,丁
魏=徵
魯=班,賓遜,智深
黃=埔,帝,埔軍校,土高原
他=媽的
混=蛋
渾=蛋
雜=種
低=能
陰=道
睪=丸
賤=人
妓=女
娼=妓
變=態
強=姦
做=愛
自=慰
"""

# China-related phrases the user asked to delete (2026-09-29), by the categories
# they were reviewed in; the first character is the lead, the rest the ending
REMOVED_CHINA = {
    "中共體制與政治用語": "常委 省委 市委 黨委 紅軍 神州 赤化 內地 自治區 邊區 土改 勞改 勞改營",
    "中國城市": "青島 寧波 溫州 珠海 汕頭 揚州 紹興 泉州 漳州 延安 徐州 鎮江 九江 宜昌 岳陽 柳州 "
                "敦煌 酒泉 承德 煙台 金陵 燕京",
    "中國地理": "淮河 松花江 嵩山 衡山 洞庭湖 鄱陽湖 雲貴高原 崑崙 戈壁 絲路 圓明園 黃海",
    "中國地區": "兩廣 關外 塞外",
    "大陸用語": "音頻 默認",
    "中國歷史": "漢朝 唐朝 宋朝 元朝 明朝 清朝 晉朝 周朝 商朝 三國 春秋 戰國 東漢 西漢 西晉 北宋 "
                "南宋 滿清 清廷 皇帝 光緒 宣統 八國聯軍 甲午 辛亥 北伐 抗戰 抗日 七七",
    "其他": "東北 西北 西南 書記 支部 統一 特區 祖國 同志 兩岸 淪陷區 閩南 人民團體 土豆 故宮 華山 "
            "三峽 東海 南海 大同 衡陽 北海 泰安 長安 南京東路 程序 數據 渠道 摩托車 自行車 領導 "
            "單位 愛人 水平 抓緊 落實 貫徹 師傅",
}

# phrases related to the Kuomintang (中國國民黨), deleted at the user's request the
# same day, including the general party vocabulary they chose to delete as well
REMOVED_KMT = {
    "國民黨黨名與黨務": "國民黨 黨國 黨國元老 中央黨部 市黨部 黨工",
    "孫中山與三民主義": "國父 國父紀念館 三民主義 逸仙 中山 中山堂 建國大綱 革命先烈",
    "蔣家": "中正機場",
    "國民黨政治人物": "林森 錢復 沈劍虹",
    "威權統治與戒嚴": "戡亂 戡亂時期 戒嚴 戒嚴法 戒嚴令 戒嚴案 警總 政戰部 政戰學校 救國團 國民大會 國代 "
                      "黨禁 黨外 威權 光復 光復節",
    "黨營媒體": "中廣 中視",
    "軍隊與眷村": "國軍 眷村 老兵 榮民 榮民總醫院 榮民之家 榮民工程處 莒光 莒光日 莒光號",
    "省籍": "外省 本省 本省人",
    "中華民國國號與象徵": "中華民國 民國 國旗 國語 青天 白日",
    "一般政黨用語": "黨部 黨員 黨內 黨籍 黨團 黨政 黨派 黨務 黨主席 黨費 黨魁 黨旗 黨徽 黨紀 黨鞭 黨章 黨綱 "
                    "黨義 黨證 黨校 黨性 黨法 黨人 黨友 黨爭 入黨 建黨 脫黨 跨黨 革命軍 革命黨 總裁 副總裁 領袖",
}

# Chinese political figures (emperors, officials, generals), deleted the same day.
# 汪洋 stays: in this dictionary it is the ordinary word (汪洋大海), not the politician
REMOVED_POLITICIANS = "始皇 忽必烈 順治 嘉慶 道光 同治 榮祿 衛青 蒙恬 包青天 柳宗元"


def removed_pairs():
    for line in REMOVED.strip().splitlines():
        lead, _, rest = line.partition("=")
        for ending in rest.split(","):
            yield lead, ending


class PhraseDictionaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(PHRASE_JSON, encoding="utf-8") as f:
            cls.data = json.load(f)
        cls.chardefs = cls.data["chardefs"]

    def test_removed_phrases_are_absent(self):
        pairs = list(removed_pairs())
        self.assertEqual(len(pairs), 197)
        present = [lead + ending for lead, ending in pairs if ending in self.chardefs.get(lead, [])]
        self.assertEqual(present, [])

    def test_removed_china_related_phrases_are_absent(self):
        words = " ".join(REMOVED_CHINA.values()).split()
        self.assertEqual(len(words), 119)
        present = [w for w in words if w[1:] in self.chardefs.get(w[0], [])]
        self.assertEqual(present, [])

    def test_removed_kmt_related_phrases_are_absent(self):
        words = " ".join(REMOVED_KMT.values()).split()
        self.assertEqual(len(words), 90)
        present = [w for w in words if w[1:] in self.chardefs.get(w[0], [])]
        self.assertEqual(present, [])

    def test_removed_political_figures_are_absent(self):
        words = REMOVED_POLITICIANS.split()
        self.assertEqual(len(words), 11)
        present = [w for w in words if w[1:] in self.chardefs.get(w[0], [])]
        self.assertEqual(present, [])

    def test_structure(self):
        self.assertEqual(set(self.data), {"chardefs", "keynames"})
        empty = [lead for lead, endings in self.chardefs.items() if not endings]
        self.assertEqual(empty, [])
        duplicated = [lead for lead, endings in self.chardefs.items() if len(endings) != len(set(endings))]
        self.assertEqual(duplicated, [])
        missing_keynames = set(self.chardefs) - set(self.data["keynames"])
        self.assertEqual(missing_keynames, set())


if __name__ == "__main__":
    unittest.main()
