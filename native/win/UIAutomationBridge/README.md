# Shail UIAutomationBridge (Windows)

Real-time UI Automation monitoring service for Windows.

## Status

⚠️ **Placeholder Implementation** - Requires completion

## Features (Planned)

- Real-time focus change monitoring
- Window event tracking (opened, closed, moved, resized)
- UI element inspection (role, name, value, bounding rectangle)
- WebSocket server on `ws://localhost:8766/accessibility`
- Heartbeat messages every 1 second

## Requirements

- Windows 10 or later
- .NET 6.0 or later
- Visual Studio 2022 (recommended)

## Building

```powershell
cd native\win\UIAutomationBridge
dotnet build -c Release
```

Or open `UIAutomationBridge.csproj` in Visual Studio and build.

## Implementation Notes

### UI Automation API
Windows UI Automation provides access to all UI elements:

```csharp
// Monitor focus changes
Automation.AddAutomationFocusChangedEventHandler(OnFocusChanged);

// Monitor window events
Automation.AddAutomationEventHandler(
    WindowPattern.WindowOpenedEvent,
    AutomationElement.RootElement,
    TreeScope.Subtree,
    OnWindowOpened
);

// Get element info
var element = AutomationElement.FocusedElement;
var name = element.Current.Name;
var type = element.Current.ControlType.ProgrammaticName;
var rect = element.Current.BoundingRectangle;
```

### Pattern-Based Access
Use control patterns to interact with elements:

```csharp
// Get text value
if (element.TryGetCurrentPattern(ValuePattern.Pattern, out object pattern))
{
    var value = ((ValuePattern)pattern).Current.Value;
}

// Invoke button
if (element.TryGetCurrentPattern(InvokePattern.Pattern, out object pattern))
{
    ((InvokePattern)pattern).Invoke();
}
```

## WebSocket Protocol

Same as macOS version - see `native/mac/AccessibilityBridge/README.md`

## License

Part of the Shail AI system.

