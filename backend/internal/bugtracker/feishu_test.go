// 飞书群自定义机器人通知的单元测试（离线，不依赖真实飞书）。
//
// 覆盖三个关键点：
//  1. 发送成功路径（响应 code=0）；
//  2. "HTTP 200 假成功"缺陷回归：飞书失败时（签名错误/限流）也返回 HTTP 200，
//     错误藏在 body 的 code 字段，发送方必须识别为失败；
//  3. 签名字段只在配置 secret（机器人开启签名校验）时携带。
//
// 真实 webhook 冒烟用例见文件尾部 TestLiveWebhookSmoke（默认跳过，环境变量门控）。
package bugtracker

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"sync"
	"testing"
	"time"
)

// fakeFeishu 模拟飞书自定义机器人 webhook：记录收到的消息体，按预设 code/msg 应答。
type fakeFeishu struct {
	*httptest.Server

	mu   sync.Mutex
	msgs []feishuTextMsg
}

func newFakeFeishu(code int, msg string) *fakeFeishu {
	f := &fakeFeishu{}
	f.Server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var m feishuTextMsg
		_ = json.NewDecoder(r.Body).Decode(&m)
		f.mu.Lock()
		f.msgs = append(f.msgs, m)
		f.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{"code": code, "msg": msg})
	}))
	return f
}

func (f *fakeFeishu) received() []feishuTextMsg {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]feishuTextMsg(nil), f.msgs...)
}

func notifierFor(url string) *FeishuNotifier {
	return &FeishuNotifier{webhookURL: url, client: &http.Client{Timeout: 3 * time.Second}}
}

func TestPostSuccess(t *testing.T) {
	f := newFakeFeishu(0, "success")
	defer f.Close()

	if err := notifierFor(f.URL).post("hello"); err != nil {
		t.Fatalf("期望发送成功，得到错误: %v", err)
	}
	msgs := f.received()
	if len(msgs) != 1 {
		t.Fatalf("期望收到 1 条消息，实际 %d", len(msgs))
	}
	if msgs[0].MsgType != "text" || msgs[0].Content.Text != "hello" {
		t.Fatalf("消息体不符合飞书 text 协议: %+v", msgs[0])
	}
}

// TestPostBusinessErrorWithHTTP200 回归"假成功"缺陷：
// 飞书在签名错误/机器人被移出群/限流时同样返回 HTTP 200，必须以 body code!=0 判定失败。
func TestPostBusinessErrorWithHTTP200(t *testing.T) {
	f := newFakeFeishu(19021, "sign match fail")
	defer f.Close()

	if err := notifierFor(f.URL).post("hello"); err == nil {
		t.Fatal("code!=0 应识别为发送失败（HTTP 200 不代表成功）")
	}
}

// TestSignFieldsOnlyWithSecret 开启签名校验（配置 secret）时携带 timestamp+sign；未开启不携带。
func TestSignFieldsOnlyWithSecret(t *testing.T) {
	f := newFakeFeishu(0, "success")
	defer f.Close()

	withSecret := &FeishuNotifier{webhookURL: f.URL, secret: "test-secret", client: &http.Client{Timeout: 3 * time.Second}}
	if err := withSecret.post("signed"); err != nil {
		t.Fatalf("带 secret 发送失败: %v", err)
	}
	m := f.received()[0]
	if m.Timestamp == "" || m.Sign == "" {
		t.Fatalf("开启签名校验后应携带 timestamp/sign: %+v", m)
	}

	if err := notifierFor(f.URL).post("plain"); err != nil {
		t.Fatalf("无 secret 发送失败: %v", err)
	}
	m2 := f.received()[1]
	if m2.Timestamp != "" || m2.Sign != "" {
		t.Fatalf("未开启签名校验不应携带 timestamp/sign: %+v", m2)
	}
}

// TestSendFallsBackToLog 未配置 webhook 时静默降级为日志（不 panic、不发起请求）。
func TestSendFallsBackToLog(t *testing.T) {
	(&FeishuNotifier{}).send("fallback") // 仅覆盖降级分支
}

// TestLiveWebhookSmoke 真实飞书 webhook 冒烟（默认跳过）。
// 运行：FEISHU_WEBHOOK_URL=<真实地址> FEISHU_LIVE_SMOKE=1 go test -run TestLiveWebhookSmoke ./internal/bugtracker/
func TestLiveWebhookSmoke(t *testing.T) {
	if os.Getenv("FEISHU_LIVE_SMOKE") == "" {
		t.Skip("设置 FEISHU_LIVE_SMOKE=1 并配置 FEISHU_WEBHOOK_URL 后运行真实冒烟")
	}
	n := NewFeishuNotifier()
	if n.webhookURL == "" {
		t.Fatal("缺少 FEISHU_WEBHOOK_URL")
	}
	if err := n.post("🔧 [Bug平台] 通知链路自检：飞书机器人接入成功"); err != nil {
		t.Fatalf("真实 webhook 发送失败: %v", err)
	}
}