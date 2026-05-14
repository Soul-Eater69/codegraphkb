package main

import "testing"

func TestGetUserReturnsEmail(t *testing.T) {
	user := getUser("1")
	if user.Email != "ada@example.com" {
		t.Fatalf("unexpected email: %s", user.Email)
	}
}
