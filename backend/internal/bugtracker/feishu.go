package bugtracker

import (
"bytes"
"encoding/json"
"fmt"
"log"
"net/http"
"os"
"time"
)

// FeishuNotifier 通过飞书群机器人 webhook 发送 Bug 通知。
//
// 配置：环境变量 FEISHU_WEBHOOK_URL（群设置 → 群机器人 → 自定义机器人）。
// 未配置时降级为日志输出，不阻塞主流程（通知失败不影响 Bug 创建）。
type FeishuNotifier struct {
webhookURL string
client     *http.Client
}

func NewFeishuNotifier() *FeishuNotifier {
return &FeishuNotifier{
webhookURL: os.Getenv("FEISHU_WEBHOOK_URL"),
client:     &http.Client{Timeout: 5 * time.Second},
}
}

// feishuTextMsg 飞书自定义机器人 text 消息体。
type feishuTextMsg struct {
MsgType string `json:"msg_type"`
Content struct {
Text string `json:"text"`
} `json:"content"`
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

// send 底层发送：未配置 webhook 或发送失败仅记日志，绝不影响业务主流程。
func (f *FeishuNotifier) send(text string) {
if f.webhookURL == "" {
log.Printf("[feishu] 未配置 FEISHU_WEBHOOK_URL，通知降级为日志: %s", text)
return
}
var msg feishuTextMsg
msg.MsgType = "text"
msg.Content.Text = text
body, err := json.Marshal(msg)
if err != nil {
log.Printf("[feishu] marshal failed: %v", err)
return
}
resp, err := f.client.Post(f.webhookURL, "application/json", bytes.NewReader(body))
if err != nil {
log.Printf("[feishu] send failed: %v", err)
return
}
defer resp.Body.Close()
if resp.StatusCode != http.StatusOK {
log.Printf("[feishu] send got status %d", resp.StatusCode)
}
}
