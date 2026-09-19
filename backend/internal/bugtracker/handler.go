package bugtracker

import (
"context"
"errors"
"net/http"
"strings"
"time"

"feedsystem_video_go/internal/account"
"feedsystem_video_go/internal/apierror"
"feedsystem_video_go/internal/middleware/jwt"

"github.com/gin-gonic/gin"
"gorm.io/gorm"
)

type Repository struct{ db *gorm.DB }
type Service struct {
repo     *Repository
accounts *account.AccountRepository
notify   *FeishuNotifier
}
type Handler struct{ service *Service }

func NewRepository(db *gorm.DB) *Repository { return &Repository{db: db} }
func NewService(repo *Repository, accounts *account.AccountRepository, notify *FeishuNotifier) *Service {
return &Service{repo: repo, accounts: accounts, notify: notify}
}
func NewHandler(service *Service) *Handler { return &Handler{service: service} }

// ---------- Repository ----------

func (r *Repository) Create(ctx context.Context, bug *Bug) error {
return r.db.WithContext(ctx).Create(bug).Error
}

func (r *Repository) GetByID(ctx context.Context, id uint) (*Bug, error) {
var bug Bug
if err := r.db.WithContext(ctx).First(&bug, id).Error; err != nil {
return nil, err
}
return &bug, nil
}

// UpdateStatus 状态机流转：只允许合法迁移，非法迁移返回错误。
func (r *Repository) UpdateStatus(ctx context.Context, id uint, from, to BugStatus, stampColumn string) error {
result := r.db.WithContext(ctx).Model(&Bug{}).
Where("id = ? AND status = ?", id, from).
Update("status", to)
if result.Error != nil {
return result.Error
}
if result.RowsAffected == 0 {
return errors.New("bug 不存在或当前状态不允许该流转")
}
if stampColumn != "" {
now := time.Now()
return r.db.WithContext(ctx).Model(&Bug{}).Where("id = ?", id).
Update(stampColumn, &now).Error
}
return nil
}

// List 按状态/角色过滤，返回 bug 列表与总数。
func (r *Repository) List(ctx context.Context, userID uint, status string, role string, limit int) ([]Bug, int64, error) {
query := r.db.WithContext(ctx).Model(&Bug{})
switch role {
case "reported":
query = query.Where("reporter_id = ?", userID)
case "assigned":
query = query.Where("assignee_id = ?", userID)
}
if status != "" {
query = query.Where("status = ?", BugStatus(status))
}
var total int64
if err := query.Count(&total).Error; err != nil {
return nil, 0, err
}
if limit <= 0 || limit > 100 {
limit = 50
}
var bugs []Bug
err := query.Order("id desc").Limit(limit).Find(&bugs).Error
return bugs, total, err
}

// ---------- Service ----------

var validSeverities = map[string]bool{"critical": true, "major": true, "minor": true, "trivial": true}

// 合法状态迁移表：from -> 允许的 to 集合
var transitions = map[BugStatus]map[BugStatus]bool{
StatusOpen:   {StatusFixing: true, StatusFixed: true, StatusClosed: true},
StatusFixing: {StatusFixed: true},
StatusFixed:  {StatusClosed: true, StatusOpen: true}, // closed=回归通过 / open=回归失败打回
StatusClosed: {},                                     // 终态
}

func (s *Service) Create(ctx context.Context, reporterID uint, req *CreateBugRequest) (*Bug, error) {
req.Title = strings.TrimSpace(req.Title)
if req.Title == "" {
return nil, apierror.Wrap(apierror.ErrValidation, errors.New("title is required"))
}
if req.AssigneeID == 0 {
return nil, apierror.Wrap(apierror.ErrValidation, errors.New("assignee_id is required"))
}
if req.Severity == "" {
req.Severity = "minor"
}
if !validSeverities[req.Severity] {
return nil, apierror.Wrap(apierror.ErrValidation, errors.New("severity 必须是 critical/major/minor/trivial"))
}
// 负责人必须存在
assignee, err := s.accounts.FindByID(ctx, req.AssigneeID)
if err != nil {
return nil, apierror.Wrap(apierror.ErrValidation, errors.New("assignee 不存在"))
}
reporter, _ := s.accounts.FindByID(ctx, reporterID)
reporterName, assigneeName := "未知用户", assignee.Username
if reporter != nil {
reporterName = reporter.Username
}

bug := &Bug{
Title:       req.Title,
Description: req.Description,
Severity:    Severity(req.Severity),
Status:      StatusOpen,
ReporterID:  reporterID,
AssigneeID:  req.AssigneeID,
}
if err := s.repo.Create(ctx, bug); err != nil {
return nil, err
}
// 通知负责人（异步语义：失败不影响创建结果）
s.notify.NotifyAssignee(bug, assigneeName, reporterName)
return bug, nil
}

func (s *Service) UpdateStatus(ctx context.Context, operatorID uint, bugID uint, newStatus string) (*Bug, error) {
to := BugStatus(newStatus)
bug, err := s.repo.GetByID(ctx, bugID)
if err != nil {
return nil, err
}
// 权限：只有负责人能标记 fixing/fixed，只有提交人能 closed（回归通过）/open（打回）
allowed := false
switch to {
case StatusFixing, StatusFixed:
allowed = operatorID == bug.AssigneeID
case StatusClosed, StatusOpen:
allowed = operatorID == bug.ReporterID
}
if !allowed {
return nil, apierror.Wrap(apierror.ErrUnauthorized, errors.New("无权限执行该状态变更"))
}
if !transitions[bug.Status][to] {
return nil, apierror.Wrap(apierror.ErrValidation,
errors.New("非法状态流转: "+string(bug.Status)+" -> "+string(to)))
}

stamp := ""
switch to {
case StatusFixed:
stamp = "fixed_at"
case StatusClosed:
stamp = "closed_at"
}
if err := s.repo.UpdateStatus(ctx, bugID, bug.Status, to, stamp); err != nil {
return nil, err
}

// 状态变更后触发对应通知
assignee, _ := s.accounts.FindByID(ctx, bug.AssigneeID)
reporter, _ := s.accounts.FindByID(ctx, bug.ReporterID)
assigneeName, reporterName := "未知用户", "未知用户"
if assignee != nil {
assigneeName = assignee.Username
}
if reporter != nil {
reporterName = reporter.Username
}
switch to {
case StatusFixed:
s.notify.NotifyReporter(bug, assigneeName, reporterName)
case StatusOpen: // 从 fixed 打回
s.notify.NotifyReopen(bug, assigneeName, reporterName)
}

return s.repo.GetByID(ctx, bugID)
}

func (s *Service) List(ctx context.Context, userID uint, req *ListBugRequest) (*ListBugResponse, error) {
bugs, total, err := s.repo.List(ctx, userID, req.Status, req.Role, req.Limit)
if err != nil {
return nil, err
}
items := make([]BugWithNames, 0, len(bugs))
for _, b := range bugs {
item := BugWithNames{Bug: b}
if a, err := s.accounts.FindByID(ctx, b.ReporterID); err == nil {
item.ReporterName = a.Username
}
if a, err := s.accounts.FindByID(ctx, b.AssigneeID); err == nil {
item.AssigneeName = a.Username
}
items = append(items, item)
}
return &ListBugResponse{Bugs: items, Total: total}, nil
}

// ---------- Handler ----------

func (h *Handler) Create(c *gin.Context) {
reporterID, err := jwt.GetAccountID(c)
if err != nil {
c.JSON(http.StatusUnauthorized, gin.H{"error": err.Error()})
return
}
var req CreateBugRequest
if err := c.ShouldBindJSON(&req); err != nil {
c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
return
}
bug, err := h.service.Create(c.Request.Context(), reporterID, &req)
if err != nil {
c.JSON(apierror.ClassifyHTTPStatus(err), gin.H{"error": err.Error()})
return
}
c.JSON(http.StatusOK, bug)
}

func (h *Handler) UpdateStatus(c *gin.Context) {
operatorID, err := jwt.GetAccountID(c)
if err != nil {
c.JSON(http.StatusUnauthorized, gin.H{"error": err.Error()})
return
}
var req struct {
BugID  uint   `json:"bug_id"`
Status string `json:"status"`
}
if err := c.ShouldBindJSON(&req); err != nil {
c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
return
}
if req.BugID == 0 || req.Status == "" {
c.JSON(http.StatusBadRequest, gin.H{"error": "bug_id and status are required"})
return
}
bug, err := h.service.UpdateStatus(c.Request.Context(), operatorID, req.BugID, req.Status)
if err != nil {
c.JSON(apierror.ClassifyHTTPStatus(err), gin.H{"error": err.Error()})
return
}
c.JSON(http.StatusOK, bug)
}

func (h *Handler) List(c *gin.Context) {
userID, err := jwt.GetAccountID(c)
if err != nil {
c.JSON(http.StatusUnauthorized, gin.H{"error": err.Error()})
return
}
var req ListBugRequest
if err := c.ShouldBindJSON(&req); err != nil {
c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
return
}
resp, err := h.service.List(c.Request.Context(), userID, &req)
if err != nil {
c.JSON(apierror.ClassifyHTTPStatus(err), gin.H{"error": err.Error()})
return
}
c.JSON(http.StatusOK, resp)
}

// AutoMigrate 建表（幂等）。
func (r *Repository) AutoMigrate(ctx context.Context) error {
return r.db.WithContext(ctx).AutoMigrate(&Bug{})
}
