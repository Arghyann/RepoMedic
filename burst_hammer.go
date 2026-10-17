package main

import (
	"bytes"
	"fmt"
	"net/http"
	"sync"
	"time"
)

// Fires a sudden storm of 50 concurrent requests every 25 seconds
func main() {
	client := &http.Client{
		Timeout: 3 * time.Second,
	}

	fmt.Println("🚀 Go Burst Hammer ready. Firing 50 concurrent requests periodically...")

	for {
		time.Sleep(15 * time.Second)
		fmt.Println("💥 [BURST] Firing 50 concurrent requests to overwhelm the server!")

		var wg sync.WaitGroup
		for i := 0; i < 50; i++ {
			wg.Add(1)
			go func() {
				defer wg.Done()
				req, err := http.NewRequest("POST", "http://127.0.0.1:8080/api/v1/checkout", bytes.NewBuffer([]byte("{}")))
				if err != nil {
					return
				}
				resp, err := client.Do(req)
				if err == nil {
					resp.Body.Close()
				}
			}()
		}
		wg.Wait()
		fmt.Println("🏁 [BURST DONE] Waiting for next wave...")
	}
}
