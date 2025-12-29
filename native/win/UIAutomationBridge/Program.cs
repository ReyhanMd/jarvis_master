using System;
using System.Threading.Tasks;
using System.Windows.Automation;

namespace Shail.UIAutomationBridge
{
    /// <summary>
    /// Windows UI Automation bridge using UIAutomationClient
    /// Streams accessibility events via WebSocket to ws://localhost:8766/accessibility
    /// </summary>
    class Program
    {
        static async Task Main(string[] args)
        {
            Console.WriteLine("♿ Shail UIAutomationBridge (Windows) starting...");

            // Initialize WebSocket server
            var wsServer = new WebSocketServer(8766);
            await wsServer.StartAsync();

            // Initialize UI Automation bridge
            var bridge = new UIAutomationBridge(wsServer);
            bridge.StartMonitoring();

            Console.WriteLine("✅ UIAutomationBridge running on ws://localhost:8766/accessibility");
            Console.WriteLine("📡 Monitoring focus changes, window events, and UI interactions");

            // Keep running
            await Task.Delay(System.Threading.Timeout.Infinite);
        }
    }

    /// <summary>
    /// UI Automation event monitoring and streaming
    /// </summary>
    class UIAutomationBridge
    {
        private WebSocketServer _server;
        private System.Timers.Timer _heartbeatTimer;
        private int _eventCount = 0;

        public UIAutomationBridge(WebSocketServer server)
        {
            _server = server;
        }

        public void StartMonitoring()
        {
            // Register for focus change events
            Automation.AddAutomationFocusChangedEventHandler(OnFocusChanged);

            // Register for window opened events
            Automation.AddAutomationEventHandler(
                WindowPattern.WindowOpenedEvent,
                AutomationElement.RootElement,
                TreeScope.Subtree,
                OnWindowOpened
            );

            // Register for window closed events
            Automation.AddAutomationEventHandler(
                WindowPattern.WindowClosedEvent,
                AutomationElement.RootElement,
                TreeScope.Subtree,
                OnWindowClosed
            );

            // Start heartbeat
            _heartbeatTimer = new System.Timers.Timer(1000);
            _heartbeatTimer.Elapsed += SendHeartbeat;
            _heartbeatTimer.Start();

            Console.WriteLine("✅ UI Automation monitoring started");
        }

        private void OnFocusChanged(object sender, AutomationFocusChangedEventArgs e)
        {
            _eventCount++;

            try
            {
                var element = AutomationElement.FocusedElement;
                if (element == null) return;

                var info = GetElementInfo(element);
                info["notification_type"] = "focus_changed";

                SendAccessibilityEvent(info);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"❌ Error in focus handler: {ex.Message}");
            }
        }

        private void OnWindowOpened(object sender, AutomationEventArgs e)
        {
            _eventCount++;
            Console.WriteLine("🪟 Window opened");
            // TODO: Get window info and send event
        }

        private void OnWindowClosed(object sender, AutomationEventArgs e)
        {
            _eventCount++;
            Console.WriteLine("🪟 Window closed");
            // TODO: Get window info and send event
        }

        private Dictionary<string, object> GetElementInfo(AutomationElement element)
        {
            var info = new Dictionary<string, object>
            {
                ["timestamp"] = DateTime.UtcNow.ToString("o"),
                ["element_id"] = Guid.NewGuid().ToString()
            };

            try
            {
                // Get process name
                var processId = element.Current.ProcessId;
                var process = System.Diagnostics.Process.GetProcessById(processId);
                info["app_name"] = process.ProcessName;

                // Get element properties
                info["role"] = element.Current.ControlType.ProgrammaticName;
                info["name"] = element.Current.Name ?? "";
                info["automation_id"] = element.Current.AutomationId ?? "";
                info["class_name"] = element.Current.ClassName ?? "";

                // Get bounding rectangle
                var rect = element.Current.BoundingRectangle;
                if (!rect.IsEmpty)
                {
                    info["x"] = (int)rect.X;
                    info["y"] = (int)rect.Y;
                    info["width"] = (int)rect.Width;
                    info["height"] = (int)rect.Height;
                    info["bbox"] = new[] {
                        (int)rect.X,
                        (int)rect.Y,
                        (int)(rect.X + rect.Width),
                        (int)(rect.Y + rect.Height)
                    };
                }

                // Get value if available
                if (element.TryGetCurrentPattern(ValuePattern.Pattern, out object valuePattern))
                {
                    var value = ((ValuePattern)valuePattern).Current.Value;
                    if (!string.IsNullOrEmpty(value))
                    {
                        info["text"] = value;
                    }
                }

                // Get window title if inside a window
                var walker = TreeWalker.ControlViewWalker;
                var parent = element;
                for (int i = 0; i < 10; i++)
                {
                    parent = walker.GetParent(parent);
                    if (parent == null) break;

                    if (parent.Current.ControlType == ControlType.Window)
                    {
                        info["window_title"] = parent.Current.Name ?? "";
                        break;
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"⚠️  Error getting element info: {ex.Message}");
            }

            return info;
        }

        private void SendAccessibilityEvent(Dictionary<string, object> info)
        {
            info["type"] = "accessibility_event";
            var json = System.Text.Json.JsonSerializer.Serialize(info);
            _server.BroadcastJSON(json).Wait();
        }

        private void SendHeartbeat(object sender, System.Timers.ElapsedEventArgs e)
        {
            var heartbeat = new
            {
                type = "heartbeat",
                timestamp = DateTime.UtcNow.ToString("o"),
                events_captured = _eventCount,
                monitoring = true
            };

            var json = System.Text.Json.JsonSerializer.Serialize(heartbeat);
            _server.BroadcastJSON(json).Wait();
        }
    }

    /// <summary>
    /// WebSocket server for streaming accessibility events
    /// </summary>
    class WebSocketServer
    {
        private int _port;
        // TODO: Implement WebSocket server using System.Net.WebSockets

        public WebSocketServer(int port)
        {
            _port = port;
        }

        public async Task StartAsync()
        {
            Console.WriteLine($"🌐 WebSocket server would listen on port {_port}");
            Console.WriteLine("⚠️  WebSocket server implementation pending");
            await Task.CompletedTask;
        }

        public async Task BroadcastJSON(string json)
        {
            // TODO: Send text message to all connected clients
            await Task.CompletedTask;
        }
    }
}

