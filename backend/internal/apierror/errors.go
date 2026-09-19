package apierror

import (
	"errors"
	"net/http"

	"gorm.io/gorm"
)

var (
	ErrUnauthorized = errors.New("unauthorized")
	ErrValidation   = errors.New("validation error")
)

// wrapped 将业务错误与 HTTP 分类哨兵错误绑定，支持 errors.Is/As 解包。
type wrapped struct {
	cls  error // 分类哨兵：ErrUnauthorized / ErrValidation
	err  error // 原始业务错误
}

func (w *wrapped) Error() string { return w.err.Error() }
func (w *wrapped) Unwrap() error { return w.err }

// Is 兼容 errors.Is(err, cls) 的直接匹配。
func (w *wrapped) Is(target error) bool { return target == w.cls }

// Wrap 用 HTTP 分类哨兵包装业务错误，供 ClassifyHTTPStatus 归类状态码。
func Wrap(cls, err error) error {
	return &wrapped{cls: cls, err: err}
}

func ClassifyHTTPStatus(err error) int {
	switch {
	case err == nil:
		return http.StatusOK
	case errors.Is(err, ErrUnauthorized):
		return http.StatusUnauthorized
	case errors.Is(err, ErrValidation):
		return http.StatusBadRequest
	case errors.Is(err, gorm.ErrRecordNotFound):
		return http.StatusNotFound
	default:
		return http.StatusInternalServerError
	}
}
