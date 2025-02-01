import React, { useState, useEffect, useRef } from "react";
import axios from "axios";

const API_BASE = "http://localhost:8000";

const App = () => {
  const [username, setUsername] = useState("");
  const [token, setToken] = useState(null);
  const [chatPartner, setChatPartner] = useState("");
  const [connected, setConnected] = useState(false);
  const [messages, setMessages] = useState([]);
  const [message, setMessage] = useState("");
  const chatSocket = useRef(null);

  // Register User
  const register = async () => {
    try {
      const res = await axios.post(`${API_BASE}/register/${username}`);
      alert("Registered Successfully! Please log in.");
    } catch (error) {
      alert(
        "Error registering user: " + error.response?.data?.detail ||
          error.message
      );
    }
  };

  // Login User
  const login = async () => {
    try {
      const res = await axios.post(`${API_BASE}/login/${username}`);
      setToken(res.data.token);
      alert("Logged in Successfully!");
    } catch (error) {
      alert("Invalid Username");
    }
  };

  // Logout User
  const logout = async () => {
    try {
      await axios.post(`${API_BASE}/logout/${token}`);
      setToken(null);
      setConnected(false);
      if (chatSocket.current) {
        chatSocket.current.close();
        chatSocket.current = null;
      }
      alert("Logged out Successfully!");
    } catch (error) {
      alert("Error logging out");
    }
  };

  // Auto-logout after 10 minutes
  useEffect(() => {
    if (token) {
      const timer = setTimeout(logout, 10 * 60 * 1000); // 10 minutes
      return () => clearTimeout(timer); // Clear on unmount
    }
  }, [token]);

  // Start Chat
  const startChat = async () => {
    if (!chatPartner.trim()) {
      alert("Enter partner's username");
      return;
    }

    try {
      const response = await axios.get(`${API_BASE}/logged-in-users`);
      console.log("Online users:", response.data);

      const onlineUsers = response.data;
      const partnerOnline = onlineUsers.includes(chatPartner);

      if (!partnerOnline) {
        alert(`Chat partner ${chatPartner} is not online.`);
        return;
      }

      console.log(`Connecting to chat with ${chatPartner}`);

      if (chatSocket.current) {
        chatSocket.current.close(); // Close any existing socket connection
      }

      chatSocket.current = new WebSocket(
        `ws://localhost:8000/chat/${username}/${chatPartner}`
      );

      chatSocket.current.onopen = () => {
        setConnected(true);
        setMessages([]);
        console.log("WebSocket connected.");
      };

      chatSocket.current.onmessage = (event) => {
        const data = JSON.parse(event.data);
        setMessages((prev) => [...prev, data]);
      };

      chatSocket.current.onclose = (event) => {
        console.log("WebSocket closed:", event);
        setConnected(false);
        alert("Chat disconnected.");
      };

      chatSocket.current.onerror = (error) => {
        console.error("WebSocket Error:", error);
        alert("Chat connection error. Please check the server.");
      };
    } catch (error) {
      alert(
        "Could not verify chat partner: " +
          (error.response?.data?.detail || error.message)
      );
    }
  };

  // Send Message
  const sendMessage = () => {
    if (!message.trim()) return;

    if (
      !chatSocket.current ||
      chatSocket.current.readyState !== WebSocket.OPEN
    ) {
      alert("Chat is not connected. Please reconnect.");
      return;
    }

    chatSocket.current.send(JSON.stringify({ sender: username, message }));
    setMessages((prev) => [...prev, `You: ${message}`]);
    setMessage("");
  };

  // Auto-scroll chat window
  useEffect(() => {
    const chatDiv = document.getElementById("chat-box");
    if (chatDiv) chatDiv.scrollTop = chatDiv.scrollHeight;
  }, [messages]);

  // Cleanup WebSocket on unmount
  useEffect(() => {
    return () => {
      if (chatSocket.current) {
        chatSocket.current.close();
        chatSocket.current = null;
      }
    };
  }, []);

  return (
    <div>
      <h1>FastAPI WebSocket Chat</h1>

      {!token ? (
        <div>
          <input
            type="text"
            placeholder="Enter Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <button onClick={register}>Register</button>
          <button onClick={login}>Login</button>
        </div>
      ) : (
        <div>
          <button onClick={logout}>Logout</button>
          <h2>Welcome, {username}!</h2>

          {!connected ? (
            <div>
              <input
                type="text"
                placeholder="Enter Partner's Username"
                value={chatPartner}
                onChange={(e) => setChatPartner(e.target.value)}
              />
              <button onClick={startChat}>Connect to Chat</button>
            </div>
          ) : (
            <div>
              <h3>Chat with {chatPartner}</h3>
              <div
                id="chat-box"
                style={{
                  border: "1px solid black",
                  padding: "10px",
                  height: "200px",
                  overflowY: "auto",
                }}
              >
                {messages.map((msg, index) => (
                  <p key={index}>
                    <strong>{msg.sender}: </strong>
                    {msg.message}
                  </p>
                ))}
              </div>
              <input
                type="text"
                placeholder="Type message..."
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && sendMessage()}
              />
              <button onClick={sendMessage}>Send</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default App;
