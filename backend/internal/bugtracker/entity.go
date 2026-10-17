package bugtracker

import "time"

// Bug 状态机：
//
//	open --(负责人开始修复)--> fixing --(修复完成)--> fixed --(测试回归通过)--> closed
//	  ^                                                          |
//	  +------------------------(回归失败打回)---------------------+
type BugStatus string

const (
	StatusOpen   BugStatus = "open"   // 新建，待负责人处理
	StatusFixing BugStatus = "fixing" // 修复中
	StatusFixed  BugStatus = "fixed"  // 已修复，待测试回归
	StatusClosed BugStatus = "closed" // 回归通过，关闭
)

type Severity string

const (
	SeverityCritical Severity = "critical" // 致命
	SeverityMajor    Severity = "major"    // 严重
	SeverityMinor    Severity = "minor"    // 一般
	SeverityTrivial  Severity = "trivial"  // 轻微
)

type Bug struct {
	ID          uint       `gorm:"primaryKey" json:"id"`
	Title       string     `gorm:"type:varchar(255);not null" json:"title"`
	Description string     `gorm:"type:text" json:"description"`
	Severity    Severity   `gorm:"type:varchar(16);default:minor;index" json:"severity"`
	Status      BugStatus  `gorm:"type:varchar(16);default:open;index" json:"status"`
	ReporterID  uint       `gorm:"index:idx_bug_reporter;not null" json:"reporter_id"` // 提交人（测试）
	AssigneeID  uint       `gorm:"index:idx_bug_assignee;not null" json:"assignee_id"` // 负责人（开发）
	CreatedAt   time.Time  `gorm:"autoCreateTime" json:"created_at"`
	UpdatedAt   time.Time  `gorm:"autoUpdateTime" json:"updated_at"`
	FixedAt     *time.Time `json:"fixed_at,omitempty"`
	ClosedAt    *time.Time `json:"closed_at,omitempty"`
}

type CreateBugRequest struct {
	Title       string `json:"title"`
	Description string `json:"description"`
	Severity    string `json:"severity"`
	AssigneeID  uint   `json:"assignee_id"`
}

type UpdateStatusRequest struct {
	Status string `json:"status"`
}

type ListBugRequest struct {
	Status string `json:"status"` // 可选过滤
	Role   string `json:"role"`   // reported=我提交的 / assigned=指派给我的
	Limit  int    `json:"limit"`
}

type BugWithNames struct {
	Bug
	ReporterName string `json:"reporter_name"`
	AssigneeName string `json:"assignee_name"`
}

type ListBugResponse struct {
	Bugs  []BugWithNames `json:"bugs"`
	Total int64          `json:"total"`
}
