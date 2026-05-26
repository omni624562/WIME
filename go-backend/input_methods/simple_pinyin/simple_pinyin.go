package simple_pinyin

import (
	"strings"

	"github.com/omni624562/WIME/go-backend/pime"
)

type IME struct {
	*pime.TextServiceBase
	composition string
	candidates  []string
}

var dictionary = map[string][]string{
	"ni":    {"测试", "你", "呢"},
	"nihao": {"你好", "你好啊", "您好"},
}

func New(client *pime.Client) pime.TextService {
	return &IME{
		TextServiceBase: pime.NewTextServiceBase(client),
		candidates:      []string{},
	}
}

func (ime *IME) HandleRequest(req *pime.Request) *pime.Response {
	resp := pime.NewResponse(req.SeqNum, true)

	switch req.Method {
	case "filterKeyDown", "onKeyDown":
		return ime.handleKeyDown(req, resp)
	case "filterKeyUp":
		resp.ReturnValue = 0
	case "onCompositionTerminated":
		ime.clear(resp)
	case "onActivate", "onDeactivate":
		resp.ReturnValue = 1
	}

	return resp
}

func (ime *IME) handleKeyDown(req *pime.Request, resp *pime.Response) *pime.Response {
	if ime.composition != "" {
		if ime.handleSelection(req.KeyCode, resp) {
			return resp
		}
	}

	switch req.KeyCode {
	case 0x0D: // VK_RETURN
		if ime.composition != "" {
			ime.updateCandidates()
			if len(ime.candidates) > 0 {
				resp.CommitString = ime.candidates[0]
			} else {
				resp.CommitString = ime.composition
			}
			ime.clear(resp)
			resp.ReturnValue = 1
			return resp
		}
	case 0x08: // VK_BACK
		if ime.composition != "" {
			ime.composition = ime.composition[:len(ime.composition)-1]
			if ime.composition == "" {
				ime.clear(resp)
			} else {
				ime.fillComposition(resp)
			}
			resp.ReturnValue = 1
			return resp
		}
	case 0x1B: // VK_ESCAPE
		if ime.composition != "" {
			ime.clear(resp)
			resp.ReturnValue = 1
			return resp
		}
	}

	ch := normalizeLetter(req.KeyCode, req.CharCode)
	if ch >= 'a' && ch <= 'z' {
		ime.composition += string(rune(ch))
		ime.fillComposition(resp)
		resp.ReturnValue = 1
		return resp
	}

	resp.ReturnValue = 0
	return resp
}

func (ime *IME) handleSelection(keyCode int, resp *pime.Response) bool {
	if keyCode < 0x31 || keyCode > 0x39 {
		return false
	}

	ime.updateCandidates()
	index := keyCode - 0x31
	if index >= len(ime.candidates) {
		return false
	}

	resp.CommitString = ime.candidates[index]
	ime.clear(resp)
	resp.ReturnValue = 1
	return true
}

func (ime *IME) fillComposition(resp *pime.Response) {
	ime.updateCandidates()
	resp.CompositionString = ime.composition
	resp.CompositionCursor = len(ime.composition)
	resp.CursorPos = len(ime.composition)
	resp.CandidateList = ime.candidates
	resp.ShowCandidates = len(ime.candidates) > 0
}

func (ime *IME) updateCandidates() {
	key := strings.ToLower(ime.composition)
	if words, ok := dictionary[key]; ok {
		ime.candidates = append([]string{}, words...)
		return
	}
	if ime.composition == "" {
		ime.candidates = []string{}
		return
	}
	ime.candidates = []string{"测试", ime.composition, strings.ToUpper(ime.composition)}
}

func (ime *IME) clear(resp *pime.Response) {
	ime.composition = ""
	ime.candidates = []string{}
	resp.CompositionString = ""
	resp.CandidateList = []string{}
	resp.ShowCandidates = false
	resp.CursorPos = 0
	resp.CompositionCursor = 0
}

func normalizeLetter(keyCode, charCode int) int {
	if charCode != 0 {
		if charCode >= 'A' && charCode <= 'Z' {
			return charCode + 32
		}
		return charCode
	}
	if keyCode >= 0x41 && keyCode <= 0x5A {
		return keyCode + 32
	}
	return 0
}
