import SwiftUI
import WebKit

/// Wrapper for WKWebView to display React Flow graph
struct GraphWebView: NSViewRepresentable {
    @Binding var graphState: GraphState?
    var onNodeClick: ((String) -> Void)?
    
    func makeNSView(context: Context) -> WKWebView {
        // Set up message handler for node clicks first
        let contentController = WKUserContentController()
        contentController.add(context.coordinator, name: "nodeClick")
        
        // Inject JavaScript bridge
        let bridgeScript = """
        window.swiftBridge = {
            postMessage: function(nodeId) {
                if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.nodeClick) {
                    window.webkit.messageHandlers.nodeClick.postMessage(nodeId);
                }
            }
        };
        """
        let script = WKUserScript(source: bridgeScript, injectionTime: .atDocumentEnd, forMainFrameOnly: true)
        contentController.addUserScript(script)
        
        // Configure WebView
        let config = WKWebViewConfiguration()
        config.userContentController = contentController
        
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.setValue(false, forKey: "drawsBackground") // Transparent background
        
        context.coordinator.webView = webView
        
        // Load HTML file - try multiple paths
        DispatchQueue.main.async {
            var htmlURL: URL?
            
            // Try bundle resources first
            if let bundleURL = Bundle.main.url(forResource: "graph", withExtension: "html", subdirectory: "Resources") {
                htmlURL = bundleURL
            } else if let bundleURL = Bundle.main.url(forResource: "graph", withExtension: "html") {
                htmlURL = bundleURL
            } else if let htmlPath = Bundle.main.path(forResource: "graph", ofType: "html") {
                htmlURL = URL(fileURLWithPath: htmlPath)
            } else {
                // Try relative path from executable
                if let executablePath = Bundle.main.executablePath {
                    let executableDir = (executablePath as NSString).deletingLastPathComponent
                    let resourcesPath = (executableDir as NSString).appendingPathComponent("Resources/graph.html")
                    if FileManager.default.fileExists(atPath: resourcesPath) {
                        htmlURL = URL(fileURLWithPath: resourcesPath)
                    }
                }
            }
            
            if let htmlURL = htmlURL {
                let baseURL = htmlURL.deletingLastPathComponent()
                webView.loadFileURL(htmlURL, allowingReadAccessTo: baseURL)
            } else {
                // Fallback: Create inline HTML
                let htmlContent = self.getDefaultHTML()
                webView.loadHTMLString(htmlContent, baseURL: nil)
            }
        }
        
        return webView
    }
    
    func updateNSView(_ webView: WKWebView, context: Context) {
        context.coordinator.onNodeClick = onNodeClick
        
        // Update graph state in JavaScript
        if let state = graphState {
            let jsonData = serializeStateToJSON(state)
            let script = "updateGraphState(\(jsonData));"
            webView.evaluateJavaScript(script) { result, error in
                if let error = error {
                    print("❌ Error updating graph state: \(error)")
                }
            }
        }
    }
    
    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }
    
    class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        var parent: GraphWebView
        var webView: WKWebView?
        var onNodeClick: ((String) -> Void)?
        
        init(_ parent: GraphWebView) {
            self.parent = parent
        }
        
        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            // Graph loaded, ready to receive state updates
            print("✅ Graph WebView loaded")
        }
        
        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            if message.name == "nodeClick" {
                if let nodeId = message.body as? String {
                    onNodeClick?(nodeId)
                }
            }
        }
    }
    
    private func serializeStateToJSON(_ state: GraphState) -> String {
        var dict: [String: Any] = [
            "taskDescription": state.taskDescription,
            "currentStep": state.currentStep,
            "status": state.status,
            "currentNode": state.currentNode,
            "nodes": state.nodes,
            "planId": state.planId ?? "",
            "taskId": state.taskId ?? "",
            "stepCount": state.stepCount,
            "currentStepIndex": state.currentStepIndex
        ]
        
        if let error = state.error {
            dict["error"] = error
        }
        
        // Serialize edges
        dict["edges"] = state.edges.map { edge in
            var edgeDict: [String: Any] = [
                "from": edge.from,
                "to": edge.to
            ]
            if let condition = edge.condition {
                edgeDict["condition"] = condition
            }
            return edgeDict
        }
        
        // Serialize plan steps
        dict["planSteps"] = state.planSteps.map { step in
            var stepDict: [String: Any] = [
                "stepId": step.stepId,
                "description": step.description,
                "stepType": step.stepType,
                "executed": step.executed
            ]
            if let success = step.success {
                stepDict["success"] = success
            }
            if let error = step.error {
                stepDict["error"] = error
            }
            return stepDict
        }
        
        guard let jsonData = try? JSONSerialization.data(withJSONObject: dict),
              let jsonString = String(data: jsonData, encoding: .utf8) else {
            return "{}"
        }
        
        return jsonString
    }
    
    private func getDefaultHTML() -> String {
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>LangGraph Visualization</title>
            <style>
                body { margin: 0; padding: 0; background: transparent; }
                #graph-container { width: 100%; height: 100vh; }
            </style>
        </head>
        <body>
            <div id="graph-container"></div>
            <script>
                // Graph will be initialized by React Flow
                console.log("Graph container ready");
            </script>
        </body>
        </html>
        """
    }
}

