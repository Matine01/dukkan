"use client";

import { useEffect, useRef } from "react";
import { Terminal } from "xterm";
import { FitAddon } from "xterm-addon-fit";
import "xterm/css/xterm.css";

interface ConsoleViewerProps {
  vmId: string;
  token: string;
  onDisconnect?: () => void;
}

export function ConsoleViewer({ vmId, token, onDisconnect }: ConsoleViewerProps) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const terminalInstance = useRef<Terminal | null>(null);
  const wsInstance = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!terminalRef.current) return;

    // Initialize xterm.js terminal
    const term = new Terminal({
      cursorBlink: true,
      fontSize: 14,
      fontFamily: "'Courier New', Courier, monospace",
      theme: {
        background: "#1a1a2e",
        foreground: "#eee",
        cursor: "#0f0",
        black: "#000000",
        red: "#cd3131",
        green: "#0dbc79",
        yellow: "#e5e510",
        blue: "#2472c8",
        magenta: "#bc3fbc",
        cyan: "#11a8cd",
        white: "#e5e5e5",
      },
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(terminalRef.current);
    fitAddon.fit();

    terminalInstance.current = term;

    // Connect to WebSocket
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const wsUrl = apiUrl.replace("http", "ws").replace("/api/v1", "") + `/api/v1/vms/ws/console/${vmId}?token=${token}`;
    
    const ws = new WebSocket(wsUrl);
    wsInstance.current = ws;

    ws.onopen = () => {
      term.writeln("\r\n\x1b[32mConnected to VM console\x1b[0m\r\n");
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        if (data.type === "status") {
          // Display VM status updates
          term.writeln(`\r\n\x1b[36mStatus: ${JSON.stringify(data.data)}\x1b[0m`);
        } else if (data.type === "console") {
          // Display console output
          term.write(data.output);
        }
      } catch {
        // Raw text output
        term.write(event.data);
      }
    };

    ws.onerror = (error) => {
      term.writeln("\r\n\x1b[31mConnection error\x1b[0m");
      console.error("WebSocket error:", error);
    };

    ws.onclose = () => {
      term.writeln("\r\n\x1b[31mDisconnected from VM console\x1b[0m");
      onDisconnect?.();
    };

    // Handle keyboard input
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: "input",
          data: data,
        }));
      }
    });

    // Handle window resize
    const handleResize = () => {
      fitAddon.fit();
    };

    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      ws.close();
      term.dispose();
    };
  }, [vmId, token, onDisconnect]);

  return (
    <div className="w-full h-full bg-[#1a1a2e] rounded-lg overflow-hidden">
      <div ref={terminalRef} className="w-full h-full" />
    </div>
  );
}
