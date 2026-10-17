package bugtracker

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"
)

// FeishuNotifier 通过飞书群自定义机器人 webhook 发送 Bug 通知。
//
// 配置（环境变量，模板见 .env.example）：
//   FEISHU_WEBHOOK_URL    飞书群 → 设置 → 群机器人 → 添加自定义机器人 生成的 webhook 地址；
//                         未配置时降级为日志输出，不阻塞主流程（通知失败不影响 Bug 创建）。
//   FEISHU_WEBHOOK_SECRET 机器人开启「签名校验」后生成的密钥；未开启签名则留空即可。
//
// 设计要点：
//  1. 通知异步发送（goroutine），失败仅记日志，绝不阻塞/影响 Bug 创建与状态流转；
//  2. 飞书 webhook 即使发送失败（签名错误、机器人被移出群、触发限流）HTTP 状态码
//     也是 200，真实结果在响应体 code 字段（0=成功），必须解析 body 判断，
//     否则失败会被静默当成功。
type FeishuNotifier struct {
	webhookURL string
	secret     string
	client     *http.Client
}

func NewFeishuNotifier() *FeishuNotifier {
	return &FeishuNotifier{
		webhookURL: os.Getenv("FEISHU_WEBHOOK_URL"),
		secret:     os.Getenv("FEISHU_WEBHOOK_SECRET"),
		client:     &http.Client{Timeout: 5 * time.Second},
	}
}

// feishuTextMsg 飞书自定义机器人 text 消息体。
// timestamp/sign 仅在机器人开启「签名校验」（配置了 secret）时携带。
type feishuTextMsg struct {
	MsgType string `json:"msg_type"`
	Content struct {
		Text string `json:"text"`
	} `json:"content"`
	Timestamp string `json:"timestamp,omitempty"`
	Sign      string `json:"sign,omitempty"`
}

// feishuResp 飞书 webhook 响应体：成功为 {"code":0,"msg":"success"}。
type feishuResp struct {
	Code int    `json:"code"`
	Msg  string `json:"msg"`
}

// NotifyAssignee 提交 Bug 时 @负责人来修复。
func (f *FeishuNotifier) NotifyAssignee(bug *Bug, assigneeName, reporterName string) {
	text := fmt.Sprintf(
		"🐞 [Bug平台] 新 Bug 待修复\n标题：%s\n严重度：%s\n提交人：%s\n负责人：@%s 请尽快处理（Bug #%d）\n状态：open（待修复）",
		bug.Title, bug.Severity, reporterName, assigneeName, bug.ID,
	)
	f.send(text)
}

// NotifyReporter 修复完成时通知提交人回归。
func (f *FeishuNotifier) NotifyReporter(bug *Bug, assigneeName, reporterName string) {
	text := fmt.Sprintf(
		"✅ [Bug平台] Bug 已修复，待回归\n标题：%s\n修复人：@%s\n请 %s 进行回归验证（Bug #%d）\n状态：fixed（回归通过后请关闭）",
		bug.Title, assigneeName, reporterName, bug.ID,
	)
	f.send(text)
}

// NotifyReopen 回归失败打回时通知负责人。
func (f *FeishuNotifier) NotifyReopen(bug *Bug, assigneeName, reporterName string) {
	text := fmt.Sprintf(
		"🔁 [Bug平台] Bug 回归失败，已打回\n标题：%s\n提交人：%s\n@%s 请重新修复（Bug #%d）\n状态：open（重新打开）",
		bug.Title, reporterName, assigneeName, bug.ID,
	)
	f.send(text)
}

// send 底层发送入口：未配置 webhook 时降级为日志输出；已配置则异步发送。
// 通知失败只记日志，绝不影响 Bug 创建/状态流转主流程。
func (f *FeishuNotifier) send(text string) {
	if f.webhookURL == "" {
		log.Printf("[feishu] 未配置 FEISHU_WEBHOOK_URL，通知降级为日志: %s", text)
		return
	}
	go func() {
		if err := f.post(text); err != nil {
			log.Printf("[feishu] 通知发送失败（已忽略，不影响业务）: %v", err)
		}
	}()
}

// post 同步执行一次发送并校验飞书响应码；返回 nil 表示消息已成功投递到群。
func (f *FeishuNotifier) post(text string) error {
	msg := feishuTextMsg{MsgType: "text"}
	msg.Content.Text = text
	if f.secret != "" {
		// 签名校验（飞书官方算法）：以 timestamp+"\n"+secret 作为 HMAC-SHA256 的 key，
		// 对空消息做摘要后 base64 编码。
		msg.Timestamp = strconv.FormatInt(time.Now().Unix(), 10)
		key := msg.Timestamp + "\n" + f.secret
		mac := hmac.New(sha256.New, []byte(key))
		msg.Sign = base64.StdEncoding.EncodeToString(mac.Sum(nil))
	}
	body, err := json.Marshal(msg)
	if err != nil {
		return fmt.Errorf("marshal message: %w", err)
	}
	resp, err := f.client.Post(f.webhookURL, "application/json", bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("post webhook: %w", err)
	}
	defer resp.Body.Close()

	var result feishuResp
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return fmt.Errorf("decode response (HTTP %d, 请检查 webhook 地址是否有效): %w", resp.StatusCode, err)
	}
	if result.Code != 0 {
		return fmt.Errorf("feishu reject code=%d msg=%s（常见原因：签名校验不符/机器人已被移出群/触发频率限制）", result.Code, result.Msg)
	}
	log.Printf("[feishu] 通知已发送: %s", text)
	return nil
}