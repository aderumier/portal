package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

// APIClient calls the FastAPI backend for passkey validation.
// It replaces the former direct SQLite access so the tracker can run on a
// separate host without needing access to the application database.
type APIClient struct {
	baseURL    string
	secret     string
	httpClient *http.Client
}

func NewAPIClient(baseURL, secret string) *APIClient {
	return &APIClient{
		baseURL: baseURL,
		secret:  secret,
		httpClient: &http.Client{
			Timeout: 5 * time.Second,
		},
	}
}

// CheckPasskey validates a passkey + IP against the backend.
// Returns nil if allowed, an error with the denial reason otherwise.
func (c *APIClient) CheckPasskey(ctx context.Context, passkey, clientIP string) error {
	body, _ := json.Marshal(map[string]string{
		"passkey": passkey,
		"ip":      clientIP,
	})

	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		c.baseURL+"/api/internal/tracker/check-passkey", bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Tracker-Secret", c.secret)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("backend unreachable: %w", err)
	}
	defer resp.Body.Close()

	switch resp.StatusCode {
	case http.StatusOK:
		return nil
	case http.StatusForbidden:
		var body struct {
			Detail string `json:"detail"`
		}
		json.NewDecoder(resp.Body).Decode(&body) //nolint:errcheck
		if body.Detail != "" {
			return fmt.Errorf("%s", body.Detail)
		}
		return fmt.Errorf("access denied")
	default:
		return fmt.Errorf("backend error (HTTP %d)", resp.StatusCode)
	}
}
