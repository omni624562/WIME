package fcitx5

import "github.com/omni624562/WIME/go-backend/pime"

type IME struct {
	*pime.TextServiceBase
	composition string
	candidates  []string
}

var defaultCandidates = []string{"哈", "呵", "喝", "和", "河"}

func New(client *pime.Client) pime.TextService {
	return &IME{
		TextServiceBase: pime.NewTextServiceBase(client),
		candidates:      append([]string{}, defaultCandidates...),
	}
}

func (ime *IME) HandleRequest(req *pime.Request) *pime.Response {
	resp := pime.NewResponse(req.SeqNum, true)

	switch req.Method {
	case "filterKeyDown":
		return ime.filterKeyDown(req, resp)
	case "onKeyDown":
		return ime.onKeyDown(req, resp)
	case "filterKeyUp":
		resp.ReturnValue = 0
	case "onCompositionTerminated":
		ime.clear(resp)
	case "onActivate", "onDeactivate":
		resp.ReturnValue = 1
	}

	return resp
}

func (ime *IME) filterKeyDown(req *pime.Request, resp *pime.Response) *pime.Response {
	if req.KeyCode >= 0x31 && req.KeyCode <= 0x39 {
		resp.ReturnValue = 1
		return resp
	}

	ch := normalizeLetter(req.KeyCode, req.CharCode)
	if ch >= 'a' && ch <= 'z' {
		if ime.composition == "" && ch == 'h' {
			ime.composition = "ha"
		} else {
			ime.composition += string(rune(ch))
		}
		ime.fill(resp)
		resp.ReturnValue = 1
		return resp
	}

	resp.ReturnValue = 0
	return resp
}

func (ime *IME) onKeyDown(req *pime.Request, resp *pime.Response) *pime.Response {
	if req.KeyCode >= 0x31 && req.KeyCode <= 0x39 {
		candidates := req.CandidateList
		if len(candidates) == 0 {
			candidates = ime.candidates
		}
		index := req.KeyCode - 0x31
		if index >= 0 && index < len(candidates) {
			resp.CommitString = candidates[index]
			ime.clear(resp)
			resp.ReturnValue = 1
			return resp
		}
	}

	return ime.filterKeyDown(req, resp)
}

func (ime *IME) fill(resp *pime.Response) {
	resp.CompositionString = ime.composition
	resp.CompositionCursor = len(ime.composition)
	resp.CursorPos = len(ime.composition)
	resp.CandidateList = append([]string{}, ime.candidates...)
	resp.ShowCandidates = len(ime.candidates) > 0
}

func (ime *IME) clear(resp *pime.Response) {
	ime.composition = ""
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
