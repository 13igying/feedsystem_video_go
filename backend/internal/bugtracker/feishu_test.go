// 飞书群自定义机器人通知的单元测试（离线，不依赖真实飞书）。
//
// 覆盖五个关键点：
//  1. 发送成功路径（响应 code=0），消息为富文本 post 结构；
//  2. "HTTP 200 假成功"缺陷回归：飞书失败时（签名错误/限流）也返回 HTTP 200，
//     错误藏在 body 的 code 字段，发送方必须识别为失败；
//  3. 签名字段只在配置 secret（机器人开启签名校验）时携带；
//  4. 真 @ 逻辑：FEISHU_AT_MAP 命中 → @该成员 open_id；未命中 → @所有人；
//  5. FEISHU_AT_MAP 解析的健壮性（空段/坏段跳过）。
//
// 真实 webhook 冒烟用例见文件尾部 TestLiveWebhookSmoke（默认跳过，环境变量门控）。
package bugtracker

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"
)

// fakeFeishu 模拟飞书自定义机器人 webhook：记录收到的消息体，按预设 code/msg 应答。
type fakeFeishu struct {
	*httptest.Server

	mu   sync.Mutex
	msgs []feishuPostPayload
}

func newFakeFeishu(code int, msg string) *fakeFeishu {
	f := &fakeFeishu{}
	f.Server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var m feishuPostPayload
		_ = json.NewDecoder(r.Body).Decode(&m)
		f.mu.Lock()
		f.msgs = append(f.msgs, m)
		f.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{"code": code, "msg": msg})
	}))
	return f
}

func (f *fakeFeishu) received() []feishuPostPayload {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]feishuPostPayload(nil), f.msgs...)
}

// payloadText 拼接消息中所有 text 元素，便于断言正文。
func payloadText(p feishuPostPayload) string {
	var sb strings.Builder
	if body, ok := p.Content.Post["zh_cn"]; ok {
		for _, row := range body.Content {
			for _, el := range row {
				if el.Tag == "text" {
					sb.WriteString(el.Text)
				}
			}
		}
	}
	return sb.String()
}

// payloadAt 返回消息中第一个 at 元素的 user_id（无则空串）。
func payloadAt(p feishuPostPayload) string {
	if body, ok := p.Content.Post["zh_cn"]; ok {
		for _, row := range body.Content {
			for _, el := range row {
				if el.Tag == "at" {
					return el.UserID
				}
			}
		}
	}
	return ""
}

func notifierFor(url string) *FeishuNotifier {
	return &FeishuNotifier{webhookURL: url, atMap: map[string]string{}, client: &http.Client{Timeout: 3 * time.Second}}
}

// TestParseAtMap 映射解析：容忍空白；坏段（缺 =/缺名/缺 id）跳过且不 panic。
func TestParseAtMap(t *testing.T) {
	m := parseAtMap(" 张三=ou_a , 李四=ou_b,坏段,=ou_c,王五=")
	if len(m) != 2 || m["张三"] != "ou_a" || m["李四"] != "ou_b" {
		t.Fatalf("解析结果不符合预期: %+v", m)
	}
	if len(parseAtMap("")) != 0 {
		t.Fatal("空串应解析为空映射")
	}
}

func TestPostSuccess(t *testing.T) {
	f := newFakeFeishu(0, "success")
	defer f.Close()

	if err := notifierFor(f.URL).post("hello", "world", "", ""); err != nil {
		t.Fatalf("期望发送成功，得到错误: %v", err)
	}
	msgs := f.received()
	if len(msgs) != 1 {
		t.Fatalf("期望收到 1 条消息，实际 %d", len(msgs))
	}
	m := msgs[0]
	if m.MsgType != "post" {
		t.Fatalf("消息类型应为 post（富文本），实际 %q", m.MsgType)
	}
	if got := m.Content.Post["zh_cn"].Title; got != "hello" {
		t.Fatalf("标题不符合预期: %q", got)
	}
	if !strings.Contains(payloadText(m), "world") {
		t.Fatalf("正文缺少内容: %q", payloadText(m))
	}
}

// TestPostWireFormat 回归 code=19002 缺陷：msg_type=post 时富文本主体必须嵌在
// content.post.zh_cn 下（此前误将 post 放在顶层，被飞书以 "params error, unknown
// content value" 拒收，且本地 mock/单测均未拦截）。此用例用原始 JSON 结构锁定协议
// 嵌套，防止未来改动结构体字段时再次破坏线上格式。
func TestPostWireFormat(t *testing.T) {
	f := newFakeFeishu(0, "success")
	defer f.Close()

	if err := notifierFor(f.URL).post("标题", "正文", "李四", " 尾巴"); err != nil {
		t.Fatalf("期望发送成功，得到错误: %v", err)
	}
	raw, err := json.Marshal(f.received()[0])
	if err != nil {
		t.Fatalf("marshal payload: %v", err)
	}
	var wire map[string]any
	if err := json.Unmarshal(raw, &wire); err != nil {
		t.Fatalf("unmarshal payload: %v", err)
	}
	if wire["msg_type"] != "post" {
		t.Fatalf("msg_type 应为 post: %v", wire["msg_type"])
	}
	content, ok := wire["content"].(map[string]any)
	if !ok {
		t.Fatalf("顶层缺少 content 层（飞书协议要求主体嵌在 content.post 下）: %v", wire)
	}
	post, ok := content["post"].(map[string]any)
	if !ok {
		t.Fatalf("content 下缺少 post 层: %v", content)
	}
	zh, ok := post["zh_cn"].(map[string]any)
	if !ok {
		t.Fatalf("post 下缺少 zh_cn: %v", post)
	}
	if zh["title"] != "标题" {
		t.Fatalf("标题不符合预期: %v", zh["title"])
	}
	rows, ok := zh["content"].([]any)
	if !ok || len(rows) != 2 {
		t.Fatalf("content 应为 2 行（正文 + @行）: %v", zh["content"])
	}
	atRow, ok := rows[1].([]any)
	if !ok || len(atRow) != 3 {
		t.Fatalf("@ 行应为 3 个元素（箭头文本/@元素/尾巴文本）: %v", rows[1])
	}
	at, ok := atRow[1].(map[string]any)
	if !ok || at["tag"] != "at" || at["user_id"] != "all" {
		t.Fatalf("@ 元素应为 {tag:at, user_id:all}（AT_MAP 未命中降级 @所有人）: %v", atRow[1])
	}
}

// TestPostBusinessErrorWithHTTP200 回归"假成功"缺陷：
// 飞书在签名错误/机器人被移出群/限流时同样返回 HTTP 200，必须以 body code!=0 判定失败。
func TestPostBusinessErrorWithHTTP200(t *testing.T) {
	f := newFakeFeishu(19021, "sign match fail")
	defer f.Close()

	if err := notifierFor(f.URL).post("hello", "world", "", ""); err == nil {
		t.Fatal("code!=0 应识别为发送失败（HTTP 200 不代表成功）")
	}
}

// TestSignFieldsOnlyWithSecret 开启签名校验（配置 secret）时携带 timestamp+sign；未开启不携带。
func TestSignFieldsOnlyWithSecret(t *testing.T) {
	f := newFakeFeishu(0, "success")
	defer f.Close()

	withSecret := &FeishuNotifier{webhookURL: f.URL, secret: "test-secret", atMap: map[string]string{}, client: &http.Client{Timeout: 3 * time.Second}}
	if err := withSecret.post("signed", "body", "", ""); err != nil {
		t.Fatalf("带 secret 发送失败: %v", err)
	}
	m := f.received()[0]
	if m.Timestamp == "" || m.Sign == "" {
		t.Fatalf("开启签名校验后应携带 timestamp/sign: %+v", m)
	}

	if err := notifierFor(f.URL).post("plain", "body", "", ""); err != nil {
		t.Fatalf("无 secret 发送失败: %v", err)
	}
	m2 := f.received()[1]
	if m2.Timestamp != "" || m2.Sign != "" {
		t.Fatalf("未开启签名校验不应携带 timestamp/sign: %+v", m2)
	}
}

// TestAtMentionResolvesOpenID FEISHU_AT_MAP 命中时真实 @ 该成员的 open_id。
func TestAtMentionResolvesOpenID(t *testing.T) {
	f := newFakeFeishu(0, "success")
	defer f.Close()

	n := &FeishuNotifier{
		webhookURL: f.URL,
		atMap:      map[string]string{"李四": "ou_lisi", "张三": "ou_zhangsan"},
		client:     &http.Client{Timeout: 3 * time.Second},
	}
	if err := n.post("新 Bug", "标题：x", "李四", " 请尽快处理"); err != nil {
		t.Fatalf("发送失败: %v", err)
	}
	m := f.received()[0]
	if got := payloadAt(m); got != "ou_lisi" {
		t.Fatalf("应真实 @ 李四的 open_id，得到 %q", got)
	}
}

// TestAtMentionFallsBackToAll 未命中映射（或完全未配置）时降级 @所有人，保证一定有人被提醒。
func TestAtMentionFallsBackToAll(t *testing.T) {
	f := newFakeFeishu(0, "success")
	defer f.Close()

	// 已配置映射但不含目标人
	n := &FeishuNotifier{
		webhookURL: f.URL,
		atMap:      map[string]string{"张三": "ou_zhangsan"},
		client:     &http.Client{Timeout: 3 * time.Second},
	}
	if err := n.post("新 Bug", "标题：x", "李四", " 请尽快处理"); err != nil {
		t.Fatalf("发送失败: %v", err)
	}
	if got := payloadAt(f.received()[0]); got != "all" {
		t.Fatalf("未命中映射应 @所有人(all)，得到 %q", got)
	}

	// 完全未配置映射
	if err := notifierFor(f.URL).post("新 Bug", "标题：x", "李四", " 请尽快处理"); err != nil {
		t.Fatalf("发送失败: %v", err)
	}
	if got := payloadAt(f.received()[1]); got != "all" {
		t.Fatalf("未配置映射应 @所有人(all)，得到 %q", got)
	}
}

// TestAtMentionOmittedWhenNoTarget 无需 @ 的消息（如链路自检）不应携带 at 元素。
func TestAtMentionOmittedWhenNoTarget(t *testing.T) {
	f := newFakeFeishu(0, "success")
	defer f.Close()

	if err := notifierFor(f.URL).post("自检", "body", "", ""); err != nil {
		t.Fatalf("发送失败: %v", err)
	}
	if got := payloadAt(f.received()[0]); got != "" {
		t.Fatalf("atUser 为空时不应有 at 元素，得到 %q", got)
	}
}

// TestSendFallsBackToLog 未配置 webhook 时静默降级为日志（不 panic、不发起请求）。
func TestSendFallsBackToLog(t *testing.T) {
	(&FeishuNotifier{}).send("标题", "正文", "李四", " 请处理") // 仅覆盖降级分支
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
	if err := n.post("🔧 [Bug平台] 通知链路自检", "飞书机器人接入成功（富文本+真 @ 版本）", "", ""); err != nil {
		t.Fatalf("真实 webhook 发送失败: %v", err)
	}
}
