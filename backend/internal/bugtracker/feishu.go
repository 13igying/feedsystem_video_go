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
	"strings"
	"time"
)

// FeishuNotifier 通过飞书群自定义机器人 webhook 发送 Bug 通知。
//
// 配置（环境变量，模板见 .env.example）：
//
//	FEISHU_WEBHOOK_URL    飞书群 → 设置 → 群机器人 → 添加自定义机器人 生成的 webhook 地址；
//	                      未配置时降级为日志输出，不阻塞主流程（通知失败不影响 Bug 创建）。
//	FEISHU_WEBHOOK_SECRET 机器人开启「签名校验」后生成的密钥；未开启签名则留空即可。
//	FEISHU_AT_MAP         平台用户名 → 飞书 open_id 映射（逗号分隔、等号赋值），
//	                      如：张三=ou_xxx,李四=ou_yyy。命中映射时消息真实 @ 该成员
//	                      （飞书会向其推送提醒）；未命中降级为 @所有人（user_id=all）。
//
// 设计要点：
//  1. 通知异步发送（goroutine），失败仅记日志，绝不阻塞/影响 Bug 创建与状态流转；
//  2. 飞书 webhook 即使发送失败（签名错误、机器人被移出群、触发限流）HTTP 状态码
//     也是 200，真实结果在响应体 code 字段（0=成功），必须解析 body 判断，
//     否则失败会被静默当成功；
//  3. 使用富文本（post）消息携带 at 元素实现「真 @」：纯文本消息里的 @ 只是普通
//     字符，飞书不会因它向被 @ 的人推送提醒。
type FeishuNotifier struct {
	webhookURL string
	secret     string
	atMap      map[string]string // 平台用户名 → 飞书 open_id
	client     *http.Client
}

func NewFeishuNotifier() *FeishuNotifier {
	return &FeishuNotifier{
		webhookURL: os.Getenv("FEISHU_WEBHOOK_URL"),
		secret:     os.Getenv("FEISHU_WEBHOOK_SECRET"),
		atMap:      parseAtMap(os.Getenv("FEISHU_AT_MAP")),
		client:     &http.Client{Timeout: 5 * time.Second},
	}
}

// parseAtMap 解析 "张三=ou_xxx,李四=ou_yyy" 形式的映射；容忍空段与多余空白，
// 格式非法的段跳过并记日志，绝不因配置问题 panic。
func parseAtMap(raw string) map[string]string {
	m := make(map[string]string)
	for _, pair := range strings.Split(raw, ",") {
		pair = strings.TrimSpace(pair)
		if pair == "" {
			continue
		}
		name, id, ok := strings.Cut(pair, "=")
		name, id = strings.TrimSpace(name), strings.TrimSpace(id)
		if !ok || name == "" || id == "" {
			log.Printf("[feishu] FEISHU_AT_MAP 段无效（应为 用户名=open_id）: %q", pair)
			continue
		}
		m[name] = id
	}
	return m
}

// feishuPostElem 富文本消息元素：tag=text 为文本段，tag=at 为真 @ 段。
type feishuPostElem struct {
	Tag    string `json:"tag"`
	Text   string `json:"text,omitempty"`
	UserID string `json:"user_id,omitempty"`
}

// feishuPostBody 富文本 zh_cn 内容：title + 多行 content。
type feishuPostBody struct {
	Title   string             `json:"title"`
	Content [][]feishuPostElem `json:"content"`
}

// feishuPostPayload 自定义机器人 post 消息请求体。
// timestamp/sign 仅在机器人开启「签名校验」（配置了 secret）时携带。
type feishuPostPayload struct {
	MsgType   string                    `json:"msg_type"`
	Post      map[string]feishuPostBody `json:"post"`
	Timestamp string                    `json:"timestamp,omitempty"`
	Sign      string                    `json:"sign,omitempty"`
}

// feishuResp 飞书 webhook 响应体：成功为 {"code":0,"msg":"success"}。
type feishuResp struct {
	Code int    `json:"code"`
	Msg  string `json:"msg"`
}

// NotifyAssignee 提交 Bug 时真实 @ 负责人来修复。
func (f *FeishuNotifier) NotifyAssignee(bug *Bug, assigneeName, reporterName string) {
	body := fmt.Sprintf(
		"标题：%s\n严重度：%s\n提交人：%s\nBug #%d\n状态：open（待修复）",
		bug.Title, bug.Severity, reporterName, bug.ID,
	)
	f.send("🐞 [Bug平台] 新 Bug 待修复", body, assigneeName, " 请尽快处理")
}

// NotifyReporter 修复完成时真实 @ 提交人进行回归。
func (f *FeishuNotifier) NotifyReporter(bug *Bug, assigneeName, reporterName string) {
	body := fmt.Sprintf(
		"标题：%s\n修复人：%s\nBug #%d\n状态：fixed（回归通过后请关闭）",
		bug.Title, assigneeName, bug.ID,
	)
	f.send("✅ [Bug平台] Bug 已修复，待回归", body, reporterName, " 请进行回归验证")
}

// NotifyReopen 回归失败打回时真实 @ 负责人重新修复。
func (f *FeishuNotifier) NotifyReopen(bug *Bug, assigneeName, reporterName string) {
	body := fmt.Sprintf(
		"标题：%s\n提交人：%s\nBug #%d\n状态：open（重新打开）",
		bug.Title, reporterName, bug.ID,
	)
	f.send("🔁 [Bug平台] Bug 回归失败，已打回", body, assigneeName, " 请重新修复")
}

// atElem 生成真 @ 元素：FEISHU_AT_MAP 命中 → 该成员 open_id（飞书会向其推送提醒）；
// 未命中 → @所有人（user_id=all），确保一定有人被提醒。
func (f *FeishuNotifier) atElem(name string) feishuPostElem {
	if id, ok := f.atMap[name]; ok {
		return feishuPostElem{Tag: "at", UserID: id}
	}
	log.Printf("[feishu] FEISHU_AT_MAP 未配置 %q 的 open_id，降级为 @所有人", name)
	return feishuPostElem{Tag: "at", UserID: "all"}
}

// send 底层发送入口：未配置 webhook 时降级为日志输出；已配置则异步发送。
// 通知失败只记日志，绝不影响 Bug 创建/状态流转主流程。
// atUser 为空表示该消息不需要 @（如链路自检）。
func (f *FeishuNotifier) send(title, body, atUser, atTail string) {
	if f.webhookURL == "" {
		log.Printf("[feishu] 未配置 FEISHU_WEBHOOK_URL，通知降级为日志: %s | %s", title, body)
		return
	}
	go func() {
		if err := f.post(title, body, atUser, atTail); err != nil {
			log.Printf("[feishu] 通知发送失败（已忽略，不影响业务）: %v", err)
		}
	}()
}

// post 同步发送一条富文本（post）消息并校验飞书响应码；返回 nil 表示消息已成功投递到群。
// 结构：title 标题 + body 多行正文 +（atUser 非空时）末行真实 @ 执行人。
func (f *FeishuNotifier) post(title, body, atUser, atTail string) error {
	content := [][]feishuPostElem{{{Tag: "text", Text: body}}}
	if atUser != "" {
		content = append(content, []feishuPostElem{
			{Tag: "text", Text: "→ "},
			f.atElem(atUser),
			{Tag: "text", Text: atTail},
		})
	}
	payload := feishuPostPayload{
		MsgType: "post",
		Post: map[string]feishuPostBody{
			"zh_cn": {Title: title, Content: content},
		},
	}
	if f.secret != "" {
		// 签名校验（飞书官方算法）：以 timestamp+"\n"+secret 作为 HMAC-SHA256 的 key，
		// 对空消息做摘要后 base64 编码（算法与消息类型无关）。
		payload.Timestamp = strconv.FormatInt(time.Now().Unix(), 10)
		key := payload.Timestamp + "\n" + f.secret
		mac := hmac.New(sha256.New, []byte(key))
		payload.Sign = base64.StdEncoding.EncodeToString(mac.Sum(nil))
	}
	reqBody, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("marshal message: %w", err)
	}
	resp, err := f.client.Post(f.webhookURL, "application/json", bytes.NewReader(reqBody))
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
	log.Printf("[feishu] 通知已发送: %s", title)
	return nil
}
