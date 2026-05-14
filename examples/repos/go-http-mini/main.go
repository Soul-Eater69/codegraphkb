package main

import (
	"encoding/json"
	"net/http"
)

type User struct {
	ID    string `json:"id"`
	Email string `json:"email"`
}

func getUser(id string) User {
	return User{ID: id, Email: "ada@example.com"}
}

func userHandler(w http.ResponseWriter, r *http.Request) {
	user := getUser(r.URL.Query().Get("id"))
	_ = json.NewEncoder(w).Encode(user)
}

func main() {
	http.HandleFunc("/users", userHandler)
	_ = http.ListenAndServe(":8080", nil)
}
