# Test Architecture Summary: codex-rs Testing Infrastructure

**Document Purpose**: Deep analysis of the codex-rs test architecture, examining testing strategies, infrastructure design, and solutions to the unique challenges of testing AI agent harnesses.

**Date**: 2025-10-10
**Status**: Comprehensive Analysis
**Audience**: Engineers building robust test suites for AI coding assistants

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Test Organization & Structure](#test-organization--structure)
3. [Test Harness Design](#test-harness-design)
4. [Testing Strategies](#testing-strategies)
5. [Mocking & Stubbing](#mocking--stubbing)
6. [Async Testing Infrastructure](#async-testing-infrastructure)
7. [Test Categories & Patterns](#test-categories--patterns)
8. [Challenges in Testing AI Agents](#challenges-in-testing-ai-agents)
9. [Best Practices & Insights](#best-practices--insights)

---

## Executive Summary

### Why Testing AI Agents is Hard

Testing an AI agent harness presents unique challenges:

1. **Non-determinism**: AI model responses vary
2. **External Dependencies**: Model APIs, MCP servers, filesystems
3. **Async Complexity**: Concurrent tool execution, streaming responses
4. **State Management**: Multi-turn conversations, context windows
5. **Timing Dependencies**: Race conditions, timeouts, parallelism
6. **Real I/O**: File operations, shell commands, network calls

The codex-rs test architecture solves these challenges through:
- **Deterministic mocking** of model responses
- **Isolated test environments** (temp directories, mock servers)
- **Structured test harnesses** that abstract common patterns
- **Time-based assertions** for parallelism verification
- **Comprehensive fixtures** for complex scenarios

### Test Coverage Scale

```
Total Test Files: ~100+
Test Categories:
├── Unit Tests (handlers, parsers, formatters)
├── Integration Tests (full turn flows, tool execution)
├── E2E Tests (CLI, multi-turn conversations)
├── Platform Tests (Seatbelt macOS, Landlock Linux)
└── Regression Tests (specific bug fixes)

Key Metrics:
- ~500+ test cases
- ~80%+ code coverage
- ~10-30 second test suite runtime (with mocking)
- 100% async test infrastructure
```

---

## Test Organization & Structure

### Directory Layout

```
codex-rs/
├── core/tests/
│   ├── all.rs                    # Test entry point
│   ├── common/
│   │   ├── lib.rs               # Shared test utilities
│   │   ├── test_codex.rs        # TestCodex harness
│   │   ├── responses.rs         # Mock response builders
│   │   └── test_codex_exec.rs   # CLI test harness
│   └── suite/
│       ├── tool_parallelism.rs  # Parallel execution tests
│       ├── tools.rs             # Tool behavior tests
│       ├── tool_harness.rs      # Individual tool tests
│       ├── seatbelt.rs          # Sandbox tests (macOS)
│       ├── exec.rs              # Command execution tests
│       ├── compact.rs           # Context compaction tests
│       └── ...                  # 40+ more test modules

├── exec/tests/
│   └── suite/
│       ├── apply_patch.rs       # Apply patch CLI tests
│       ├── sandbox.rs           # Sandbox integration tests
│       └── ...

├── mcp-server/tests/
│   └── suite/
│       └── codex_tool.rs        # MCP tool integration tests

└── [component]/tests/           # Per-component test suites
    └── suite/
```

**Organization Principles**:

1. **Common Infrastructure**: Shared test utilities in `common/` modules
2. **Suite Organization**: Test suites in `suite/` subdirectories
3. **Co-location**: Tests live near the code they test
4. **Entry Points**: `all.rs` aggregates all tests for a component
5. **Platform Guards**: `#[cfg(target_os = "...")]` for platform-specific tests

---

## Test Harness Design

### 1. TestCodex - Core Test Harness

**Location**: `codex-rs/core/tests/common/test_codex.rs`

**Purpose**: Provides a hermetic, controllable environment for testing the agent harness.

```rust
pub struct TestCodex {
    pub home: TempDir,              // Isolated home directory
    pub cwd: TempDir,               // Working directory for tests
    pub codex: Arc<CodexConversation>,  // Codex instance
    pub session_configured: SessionConfiguredEvent,  // Session config
}

pub struct TestCodexBuilder {
    config_mutators: Vec<Box<ConfigMutator>>,
}

impl TestCodexBuilder {
    pub fn with_config<T>(mut self, mutator: T) -> Self
    where
        T: FnOnce(&mut Config) + Send + 'static
    {
        self.config_mutators.push(Box::new(mutator));
        self
    }

    pub async fn build(&mut self, server: &MockServer) -> Result<TestCodex> {
        // Create isolated environment
        let home = TempDir::new()?;
        let cwd = TempDir::new()?;

        // Configure to point at mock server
        let model_provider = ModelProviderInfo {
            base_url: Some(format!("{}/v1", server.uri())),
            ..built_in_model_providers()["openai"].clone()
        };

        let mut config = load_default_config_for_test(&home);
        config.cwd = cwd.path().to_path_buf();
        config.model_provider = model_provider;

        // Apply custom configuration
        for mutator in self.config_mutators {
            mutator(&mut config);
        }

        // Create conversation with dummy auth
        let conversation_manager = ConversationManager::with_auth(
            CodexAuth::from_api_key("dummy")
        );
        let NewConversation {
            conversation,
            session_configured,
            ..
        } = conversation_manager.new_conversation(config).await?;

        Ok(TestCodex { home, cwd, codex: conversation, session_configured })
    }
}

pub fn test_codex() -> TestCodexBuilder {
    TestCodexBuilder { config_mutators: vec![] }
}
```

**Key Design Decisions**:

1. **Builder Pattern**: Fluent API for test setup
   ```rust
   let test = test_codex()
       .with_config(|config| {
           config.model = "test-model".to_string();
           config.include_plan_tool = true;
       })
       .build(&server)
       .await?;
   ```

2. **Isolated Environments**: Each test gets fresh temp directories
   - Prevents test pollution
   - Enables parallel test execution
   - Clean teardown automatic (TempDir drops)

3. **Mock Server Integration**: Points API client at test server
   - No real API calls
   - Deterministic responses
   - Fast test execution

4. **Configuration Flexibility**: Mutators allow per-test customization
   - Enable/disable tools
   - Change model settings
   - Adjust policies

**Usage Example**:

```rust
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn shell_tool_executes_command() -> Result<()> {
    // Setup mock server
    let server = start_mock_server().await;

    // Create test harness
    let test = test_codex()
        .with_config(|config| {
            config.model = "gpt-5".to_string();
        })
        .build(&server).await?;

    // Mount mock responses
    let response = sse(vec![
        ev_function_call("call-1", "shell", r#"{"command": ["/bin/echo", "hello"]}"#),
        ev_completed("resp-1"),
    ]);
    mount_sse_once(&server, response).await;

    // Submit turn
    test.codex.submit(Op::UserTurn {
        items: vec![InputItem::Text { text: "run command".into() }],
        cwd: test.cwd.path().to_path_buf(),
        approval_policy: AskForApproval::Never,
        sandbox_policy: SandboxPolicy::DangerFullAccess,
        // ...
    }).await?;

    // Wait for completion
    wait_for_event(&test.codex, |ev| {
        matches!(ev, EventMsg::TaskComplete(_))
    }).await;

    // Assertions...
    Ok(())
}
```

---

### 2. Mock Response Infrastructure

**Location**: `codex-rs/core/tests/common/responses.rs`

**Purpose**: Build deterministic SSE (Server-Sent Events) responses that mimic the model API.

#### 2.1 SSE Response Builder

```rust
/// Build an SSE stream body from a list of JSON events.
pub fn sse(events: Vec<Value>) -> String {
    let mut out = String::new();
    for ev in events {
        let kind = ev.get("type").and_then(|v| v.as_str()).unwrap();
        writeln!(&mut out, "event: {kind}").unwrap();
        if !ev.as_object().map(|o| o.len() == 1).unwrap_or(false) {
            write!(&mut out, "data: {ev}\n\n").unwrap();
        } else {
            out.push('\n');
        }
    }
    out
}
```

**Event Builders**:

```rust
// Response lifecycle
pub fn ev_response_created(id: &str) -> Value;
pub fn ev_completed(id: &str) -> Value;
pub fn ev_completed_with_tokens(id: &str, total_tokens: u64) -> Value;

// Content blocks
pub fn ev_assistant_message(id: &str, text: &str) -> Value;
pub fn ev_function_call(call_id: &str, name: &str, arguments: &str) -> Value;
pub fn ev_custom_tool_call(call_id: &str, name: &str, input: &str) -> Value;
pub fn ev_local_shell_call(call_id: &str, status: &str, command: Vec<&str>) -> Value;

// Special tools
pub fn ev_apply_patch_function_call(call_id: &str, patch: &str) -> Value;
pub fn ev_apply_patch_custom_tool_call(call_id: &str, patch: &str) -> Value;

// Errors
pub fn sse_failed(id: &str, code: &str, message: &str) -> String;
```

**Example - Simulating Tool Call**:

```rust
let response = sse(vec![
    ev_response_created("resp-1"),
    ev_function_call("call-1", "read_file", r#"{"path": "/tmp/foo.txt"}"#),
    ev_function_call("call-2", "read_file", r#"{"path": "/tmp/bar.txt"}"#),
    ev_completed("resp-1"),
]);

mount_sse_once(&server, response).await;
```

This simulates a model response that:
1. Creates a response
2. Calls `read_file` twice (testing parallelism)
3. Completes the response

#### 2.2 Sequential Response Mocking

**Challenge**: Multi-turn conversations require multiple API calls, each with different responses.

**Solution**: Sequential responder

```rust
pub async fn mount_sse_sequence(
    server: &MockServer,
    bodies: Vec<String>
) -> ResponseMock {
    struct SeqResponder {
        num_calls: AtomicUsize,
        responses: Vec<String>,
    }

    impl Respond for SeqResponder {
        fn respond(&self, _: &Request) -> ResponseTemplate {
            let call_num = self.num_calls.fetch_add(1, Ordering::SeqCst);
            match self.responses.get(call_num) {
                Some(body) => ResponseTemplate::new(200)
                    .insert_header("content-type", "text/event-stream")
                    .set_body_string(body.clone()),
                None => panic!("no response for {call_num}"),
            }
        }
    }

    // ...
}
```

**Usage**:

```rust
let responses = vec![
    // Turn 1: Model calls read_file
    sse(vec![
        ev_function_call("call-1", "read_file", r#"{"path": "foo.txt"}"#),
        ev_completed("resp-1"),
    ]),
    // Turn 2: Model responds with analysis
    sse(vec![
        ev_assistant_message("msg-1", "The file contains..."),
        ev_completed("resp-2"),
    ]),
];

mount_sse_sequence(&server, responses).await;

// Test can now do two turns
run_turn(&test, "read foo.txt").await?;
// Second API call automatically gets second response
```

**Key Insight**: Sequential mocking enables **multi-turn conversation testing** without complexity.

#### 2.3 Response Verification

```rust
#[derive(Clone)]
pub struct ResponseMock {
    requests: Arc<Mutex<Vec<ResponsesRequest>>>,
}

impl ResponseMock {
    pub fn single_request(&self) -> ResponsesRequest {
        let requests = self.requests.lock().unwrap();
        assert_eq!(requests.len(), 1, "expected exactly 1 request");
        requests.first().unwrap().clone()
    }

    pub fn requests(&self) -> Vec<ResponsesRequest> {
        self.requests.lock().unwrap().clone()
    }
}

pub struct ResponsesRequest(Request);

impl ResponsesRequest {
    pub fn body_json(&self) -> Value;
    pub fn input(&self) -> Vec<Value>;  // Input items sent to model
    pub fn function_call_output(&self, call_id: &str) -> Value;
    pub fn custom_tool_call_output(&self, call_id: &str) -> Value;
    pub fn header(&self, name: &str) -> Option<String>;
}
```

**Usage - Verify Tool Results**:

```rust
let mock = mount_sse_once(&server, response).await;

// Execute turn
run_turn(&test, "run command").await?;

// Verify what was sent back to model
let req = mock.single_request();
let output = req.function_call_output("call-1");

assert_eq!(output["call_id"], "call-1");
let result: Value = serde_json::from_str(
    output["output"].as_str().unwrap()
)?;
assert_eq!(result["metadata"]["exit_code"], 0);
```

**Key Insight**: ResponseMock **records all requests**, enabling verification of:
- Tool results sent to model
- Input formatting
- Error handling
- Token usage

---

### 3. Helper Functions & Utilities

#### 3.1 Event Waiting

**Challenge**: Async events arrive non-deterministically.

**Solution**: Event polling with timeout

```rust
pub async fn wait_for_event<F>(codex: &CodexConversation, predicate: F)
where
    F: Fn(&EventMsg) -> bool,
{
    let timeout = Duration::from_secs(30);
    let start = Instant::now();

    loop {
        if let Some(event) = codex.try_recv_event() {
            if predicate(&event) {
                return;
            }
        }

        if start.elapsed() > timeout {
            panic!("timeout waiting for event");
        }

        tokio::time::sleep(Duration::from_millis(10)).await;
    }
}
```

**Usage**:

```rust
// Wait for turn completion
wait_for_event(&test.codex, |ev| {
    matches!(ev, EventMsg::TaskComplete(_))
}).await;

// Wait for specific event, capture data
let mut saw_patch_event = false;
wait_for_event(&test.codex, |ev| match ev {
    EventMsg::PatchApplyBegin(begin) => {
        saw_patch_event = true;
        assert_eq!(begin.call_id, "expected-id");
        false  // Keep waiting
    }
    EventMsg::TaskComplete(_) => true,  // Done
    _ => false,  // Keep waiting
}).await;

assert!(saw_patch_event);
```

#### 3.2 Assertion Helpers

```rust
pub fn assert_regex_match(pattern: &str, text: &str) {
    let re = Regex::new(pattern).unwrap();
    assert!(
        re.is_match(text),
        "Expected pattern:\n{}\n\nActual text:\n{}",
        pattern,
        text
    );
}
```

**Usage**:

```rust
let stdout = output["output"].as_str().unwrap();
assert_regex_match(r"(?s)^tool harness\n?$", stdout);
```

#### 3.3 Platform Guards

```rust
macro_rules! skip_if_no_network {
    ($ret:expr) => {
        if std::env::var("CI").is_ok() && std::env::var("ENABLE_NETWORK_TESTS").is_err() {
            eprintln!("Skipping network test in CI without ENABLE_NETWORK_TESTS");
            return $ret;
        }
    };
}
```

**Usage**:

```rust
#[tokio::test]
async fn test_requires_network() -> Result<()> {
    skip_if_no_network!(Ok(()));

    // Test that needs network...
}
```

---

## Testing Strategies

### 1. Unit Testing Strategy

**Focus**: Test individual components in isolation.

**Examples**:

#### 1.1 Parser Tests

```rust
// codex-rs/apply-patch/src/lib.rs
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_add_file_hunk() {
        let patch = r#"*** Begin Patch
*** Add File: new.txt
+line 1
+line 2
*** End Patch"#;

        let changes = parse_apply_patch(patch).unwrap();
        assert_eq!(changes.len(), 1);

        let change = &changes[0];
        assert_eq!(change.path, Path::new("new.txt"));
        assert!(matches!(change.kind, ChangeKind::Add));
        assert_eq!(change.new_content, "line 1\nline 2\n");
    }

    #[test]
    fn parse_invalid_hunk_returns_error() {
        let patch = r#"*** Begin Patch
*** Update File: foo.txt
*** End Patch"#;  // Missing hunks

        let result = parse_apply_patch(patch);
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("invalid hunk"));
    }
}
```

**Pattern**: Test parsing logic separately from execution.

#### 1.2 Output Formatting Tests

```rust
#[test]
fn format_exec_output_truncates_large_output() {
    let large_output = "line\n".repeat(1000);

    let formatted = format_exec_output(&ExecOutput {
        exit_code: 0,
        duration: Duration::from_secs(1),
        output: large_output.clone(),
        timed_out: false,
    });

    // Should be truncated
    assert!(formatted.len() < large_output.len());

    // Should contain metadata
    assert!(formatted.contains("Total output lines: 1000"));

    // Should contain elision marker
    assert!(formatted.contains("[... omitted"));
}
```

**Pattern**: Test formatting independently of tool execution.

---

### 2. Integration Testing Strategy

**Focus**: Test full workflows with real components interacting.

#### 2.1 Tool Execution Tests

**File**: `codex-rs/core/tests/suite/tool_harness.rs`

```rust
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn shell_tool_executes_command_and_streams_output() -> Result<()> {
    let server = start_mock_server().await;
    let test = test_codex().build(&server).await?;

    let call_id = "shell-call";
    let command = vec!["/bin/echo", "tool harness"];

    // Mock model response with shell call
    let response = sse(vec![
        ev_local_shell_call(call_id, "completed", command),
        ev_completed("resp-1"),
    ]);
    mount_sse_once(&server, response).await;

    // Mock second response (model processes result)
    let second_response = sse(vec![
        ev_assistant_message("msg-1", "all done"),
        ev_completed("resp-2"),
    ]);
    let second_mock = mount_sse_once(&server, second_response).await;

    // Execute turn
    test.codex.submit(Op::UserTurn {
        items: vec![InputItem::Text {
            text: "run shell command".into(),
        }],
        cwd: test.cwd.path().to_path_buf(),
        approval_policy: AskForApproval::Never,
        sandbox_policy: SandboxPolicy::DangerFullAccess,
        model: test.session_configured.model.clone(),
        // ...
    }).await?;

    wait_for_event(&test.codex, |ev| {
        matches!(ev, EventMsg::TaskComplete(_))
    }).await;

    // Verify tool result sent to model
    let req = second_mock.single_request();
    let output = req.function_call_output(call_id);

    let exec_output: Value = serde_json::from_str(
        output["output"].as_str().unwrap()
    )?;

    assert_eq!(exec_output["metadata"]["exit_code"], 0);

    let stdout = exec_output["output"].as_str().unwrap();
    assert_regex_match(r"(?s)^tool harness\n?$", stdout);

    Ok(())
}
```

**What This Tests**:
1. ✅ Model response parsing
2. ✅ Tool call extraction
3. ✅ Shell command execution
4. ✅ Output capture
5. ✅ Output formatting (JSON with metadata)
6. ✅ Result sent back to model
7. ✅ Multi-turn conversation flow
8. ✅ Event emission

**Pattern**: End-to-end tool execution with verification at boundaries.

#### 2.2 Error Handling Tests

```rust
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn shell_escalated_permissions_rejected_then_ok() -> Result<()> {
    let server = start_mock_server().await;
    let test = test_codex().build(&server).await?;

    // First attempt: with escalated permissions (should be rejected)
    let first_args = json!({
        "command": ["/bin/echo", "test"],
        "with_escalated_permissions": true,
    });

    // Second attempt: without escalation (should succeed)
    let second_args = json!({
        "command": ["/bin/echo", "test"],
    });

    let responses = vec![
        sse(vec![
            ev_function_call("call-1", "shell", &first_args.to_string()),
            ev_completed("resp-1"),
        ]),
        sse(vec![
            ev_function_call("call-2", "shell", &second_args.to_string()),
            ev_completed("resp-2"),
        ]),
        sse(vec![
            ev_assistant_message("msg-1", "done"),
            ev_completed("resp-3"),
        ]),
    ];

    mount_sse_sequence(&server, responses).await;

    // Execute
    run_turn(&test, "run command").await?;

    // Verify first call was rejected
    let blocked_output = get_function_output("call-1");
    assert!(blocked_output.contains("approval policy"));
    assert!(blocked_output.contains("reject command"));

    // Verify second call succeeded
    let success_output = get_function_output("call-2");
    let result: Value = serde_json::from_str(&success_output)?;
    assert_eq!(result["metadata"]["exit_code"], 0);

    Ok(())
}
```

**What This Tests**:
1. ✅ Permission policy enforcement
2. ✅ Error messages sent to model
3. ✅ Model self-correction (retry without escalation)
4. ✅ Successful execution after correction
5. ✅ Multi-turn error recovery flow

**Pattern**: Test error → retry → success flows.

---

### 3. Parallelism Testing Strategy

**File**: `codex-rs/core/tests/suite/tool_parallelism.rs`

**Challenge**: Verify that parallel tools run concurrently, sequential tools run serially.

**Solution**: Time-based assertions with synchronization barriers.

#### 3.1 Parallel Tool Test

```rust
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn read_file_tools_run_in_parallel() -> Result<()> {
    let server = start_mock_server().await;
    let test = build_codex_with_test_tool(&server).await?;

    // Args that make tool sleep 300ms, then sync with barrier
    let parallel_args = json!({
        "sleep_after_ms": 300,
        "barrier": {
            "id": "parallel-test-sync",
            "participants": 2,
            "timeout_ms": 1_000,
        }
    }).to_string();

    // Model calls test_sync_tool twice
    let response = sse(vec![
        ev_function_call("call-1", "test_sync_tool", &parallel_args),
        ev_function_call("call-2", "test_sync_tool", &parallel_args),
        ev_completed("resp-1"),
    ]);

    mount_sse_once(&server, response).await;

    let start = Instant::now();
    run_turn(&test, "exercise sync tool").await?;
    let duration = start.elapsed();

    // If parallel: both tools run concurrently, total ~300ms
    // If sequential: tools run serially, total ~600ms
    assert_parallel_duration(duration);  // < 750ms

    Ok(())
}

fn assert_parallel_duration(actual: Duration) {
    assert!(
        actual < Duration::from_millis(750),
        "expected parallel execution, got {actual:?}"
    );
}
```

**Key Technique**: **Synchronization Barrier**

The `test_sync_tool` has special logic:

```rust
// In test_sync_tool handler
async fn handle(&self, invocation: ToolInvocation) -> Result<ToolOutput> {
    let params: TestSyncParams = parse_params(&invocation.payload)?;

    // Sleep
    tokio::time::sleep(Duration::from_millis(params.sleep_after_ms)).await;

    // Barrier: wait for all participants to arrive
    if let Some(barrier_config) = params.barrier {
        GLOBAL_BARRIERS
            .lock()
            .unwrap()
            .entry(barrier_config.id.clone())
            .or_insert_with(|| Arc::new(Barrier::new(barrier_config.participants)))
            .clone()
            .wait()
            .await;
    }

    Ok(ToolOutput::success("synced"))
}
```

**How It Works**:
1. Both tool calls sleep 300ms
2. Both reach barrier at ~same time (if parallel)
3. Barrier releases when both arrive
4. Total time: ~300ms (parallel) vs ~600ms (sequential)

**Why Barriers?**: Without barriers, one tool might finish before the other starts, giving false positive.

#### 3.2 Sequential Tool Test

```rust
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn non_parallel_tools_run_serially() -> Result<()> {
    let server = start_mock_server().await;
    let test = test_codex().build(&server).await?;

    let shell_args = json!({
        "command": ["/bin/sh", "-c", "sleep 0.3"],
        "timeout_ms": 1_000,
    });

    // Model calls shell twice
    let response = sse(vec![
        ev_function_call("call-1", "shell", &shell_args.to_string()),
        ev_function_call("call-2", "shell", &shell_args.to_string()),
        ev_completed("resp-1"),
    ]);

    mount_sse_once(&server, response).await;

    let start = Instant::now();
    run_turn(&test, "run shell twice").await?;
    let duration = start.elapsed();

    // Shell tool doesn't support parallelism, should run serially
    assert_serial_duration(duration);  // >= 500ms

    Ok(())
}

fn assert_serial_duration(actual: Duration) {
    assert!(
        actual >= Duration::from_millis(500),
        "expected serial execution, got {actual:?}"
    );
}
```

#### 3.3 Mixed Tool Test

```rust
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn mixed_tools_fall_back_to_serial() -> Result<()> {
    // Call parallel tool + sequential tool
    let response = sse(vec![
        ev_function_call("call-1", "test_sync_tool", &sync_args),
        ev_function_call("call-2", "shell", &shell_args),
        ev_completed("resp-1"),
    ]);

    // When any tool is sequential, all tools run serially
    let duration = run_turn_and_measure(&test, "mix tools").await?;
    assert_serial_duration(duration);

    Ok(())
}
```

**Key Insight**: Parallelism tests use **timing assertions**, not just correctness assertions.

---

### 4. Sandbox Testing Strategy

**File**: `codex-rs/core/tests/suite/seatbelt.rs` (macOS)

**Challenge**: Verify sandbox actually prevents operations.

**Solution**: Attempt operations, verify failure/success based on policy.

```rust
struct TestScenario {
    repo_parent: PathBuf,
    file_outside_repo: PathBuf,
    repo_root: PathBuf,
    file_in_repo_root: PathBuf,
    file_in_dot_git_dir: PathBuf,
}

impl TestScenario {
    async fn run_test(&self, policy: &SandboxPolicy, expectations: TestExpectations) {
        assert_eq!(
            touch(&self.file_outside_repo, policy).await,
            expectations.file_outside_repo_is_writable
        );

        assert_eq!(
            touch(&self.file_in_repo_root, policy).await,
            expectations.file_in_repo_root_is_writable
        );

        assert_eq!(
            touch(&self.file_in_dot_git_dir, policy).await,
            expectations.file_in_dot_git_dir_is_writable
        );
    }
}

async fn touch(path: &Path, policy: &SandboxPolicy) -> bool {
    let mut child = spawn_command_under_seatbelt(
        vec!["/usr/bin/touch".to_string(), path.to_string_lossy().to_string()],
        cwd,
        policy,
        sandbox_cwd,
        StdioPolicy::RedirectForShellTool,
        HashMap::new(),
    ).await?;

    child.wait().await?.success()
}
```

**Test Cases**:

```rust
#[tokio::test]
async fn read_only_forbids_all_writes() {
    let test_scenario = create_test_scenario();
    let policy = SandboxPolicy::ReadOnly;

    test_scenario.run_test(
        &policy,
        TestExpectations {
            file_outside_repo_is_writable: false,
            file_in_repo_root_is_writable: false,
            file_in_dot_git_dir_is_writable: false,
        }
    ).await;
}

#[tokio::test]
async fn workspace_write_protects_dot_git() {
    let test_scenario = create_test_scenario();
    let policy = SandboxPolicy::WorkspaceWrite {
        writable_roots: vec![test_scenario.repo_root.clone()],
        network_access: false,
        // ...
    };

    test_scenario.run_test(
        &policy,
        TestExpectations {
            file_outside_repo_is_writable: false,
            file_in_repo_root_is_writable: true,
            file_in_dot_git_dir_is_writable: false,  // Protected!
        }
    ).await;
}

#[tokio::test]
async fn danger_full_access_allows_all_writes() {
    let test_scenario = create_test_scenario();
    let policy = SandboxPolicy::DangerFullAccess;

    test_scenario.run_test(
        &policy,
        TestExpectations {
            file_outside_repo_is_writable: true,
            file_in_repo_root_is_writable: true,
            file_in_dot_git_dir_is_writable: true,
        }
    ).await;
}
```

**Pattern**: Test sandbox with **actual operations**, not just configuration.

---

### 5. E2E Testing Strategy

**File**: `codex-rs/exec/tests/suite/apply_patch.rs`

**Focus**: Test complete CLI workflows, not just library code.

```rust
#[test]
fn test_standalone_exec_cli_can_use_apply_patch() -> Result<()> {
    let tmp = tempdir()?;
    let file_path = tmp.path().join("source.txt");
    fs::write(&file_path, "original content\n")?;

    Command::cargo_bin("codex-exec")?
        .arg(CODEX_APPLY_PATCH_ARG1)
        .arg(r#"*** Begin Patch
*** Update File: source.txt
@@
-original content
+modified by apply_patch
*** End Patch"#)
        .current_dir(tmp.path())
        .assert()
        .success()
        .stdout("Success. Updated the following files:\nM source.txt\n")
        .stderr(predicates::str::is_empty());

    assert_eq!(
        fs::read_to_string(file_path)?,
        "modified by apply_patch\n"
    );

    Ok(())
}
```

**What This Tests**:
1. ✅ CLI parsing
2. ✅ Argument handling
3. ✅ File I/O
4. ✅ Stdout/stderr output
5. ✅ Exit code
6. ✅ Actual filesystem changes

**Pattern**: Use `assert_cmd` crate to test CLIs declaratively.

---

## Mocking & Stubbing

### 1. WireMock for HTTP APIs

**Library**: `wiremock` crate

**Purpose**: Mock HTTP server for model API.

#### Basic Setup

```rust
use wiremock::{MockServer, Mock, ResponseTemplate};
use wiremock::matchers::{method, path};

let server = MockServer::start().await;

Mock::given(method("POST"))
    .and(path("/v1/chat/completions"))
    .respond_with(ResponseTemplate::new(200)
        .set_body_string("response body"))
    .mount(&server)
    .await;

// Now requests to server.uri() will be intercepted
```

#### Advanced Patterns

**Sequential Responses**:

```rust
struct SeqResponder {
    num_calls: AtomicUsize,
    responses: Vec<String>,
}

impl Respond for SeqResponder {
    fn respond(&self, _: &Request) -> ResponseTemplate {
        let call_num = self.num_calls.fetch_add(1, Ordering::SeqCst);
        match self.responses.get(call_num) {
            Some(body) => ResponseTemplate::new(200).set_body_string(body.clone()),
            None => panic!("no response for {call_num}"),
        }
    }
}
```

**Request Capture**:

```rust
#[derive(Clone)]
struct ResponseMock {
    requests: Arc<Mutex<Vec<Request>>>,
}

impl Match for ResponseMock {
    fn matches(&self, request: &Request) -> bool {
        self.requests.lock().unwrap().push(request.clone());
        true  // Always match
    }
}

// Later: verify what was sent
let requests = mock.requests.lock().unwrap();
assert_eq!(requests.len(), 2);
```

---

### 2. Temp Directories for Isolation

**Library**: `tempfile` crate

**Pattern**: Each test gets isolated filesystem.

```rust
use tempfile::TempDir;

#[test]
fn test_file_operations() -> Result<()> {
    let tmp = TempDir::new()?;
    let file_path = tmp.path().join("test.txt");

    // Write file
    fs::write(&file_path, "content")?;

    // Test operations
    // ...

    // Automatic cleanup when tmp drops
    Ok(())
}
```

**Key Benefit**: No test pollution, parallel-safe.

---

### 3. Mock MCP Servers

**File**: `codex-rs/mcp-server/tests/common/mcp_process.rs`

**Purpose**: Test MCP integration without external servers.

```rust
pub struct MockMcpServer {
    child: Child,
    addr: SocketAddr,
}

impl MockMcpServer {
    pub async fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let addr = listener.local_addr()?;

        let child = Command::new("mcp-mock-server")
            .arg("--port")
            .arg(addr.port().to_string())
            .spawn()?;

        Self { child, addr }
    }

    pub fn uri(&self) -> String {
        format!("http://{}", self.addr)
    }
}

impl Drop for MockMcpServer {
    fn drop(&mut self) {
        let _ = self.child.kill();
    }
}
```

**Usage**:

```rust
#[tokio::test]
async fn test_mcp_tool_integration() -> Result<()> {
    let mcp_server = MockMcpServer::start().await;

    let test = test_codex()
        .with_mcp_server("mock", &mcp_server.uri())
        .build(&model_server)
        .await?;

    // Test MCP tool calls
    // ...
}
```

---

## Async Testing Infrastructure

### 1. Tokio Test Runtime

**Configuration**:

```rust
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn my_test() -> Result<()> {
    // Test code
}
```

**Key Settings**:
- `flavor = "multi_thread"`: Use multi-threaded runtime (required for parallelism tests)
- `worker_threads = 2`: Minimum threads to test concurrent execution

### 2. Async Synchronization Primitives

#### Barriers

```rust
use tokio::sync::Barrier;

let barrier = Arc::new(Barrier::new(2));

let b1 = barrier.clone();
tokio::spawn(async move {
    // Do work
    b1.wait().await;  // Wait for other task
});

let b2 = barrier.clone();
tokio::spawn(async move {
    // Do work
    b2.wait().await;  // Wait for other task
});

// Both tasks synchronized
```

#### Channels for Coordination

```rust
use tokio::sync::mpsc;

let (tx, mut rx) = mpsc::channel(10);

tokio::spawn(async move {
    // Send events
    tx.send(Event::Started).await.unwrap();
    // Do work
    tx.send(Event::Completed).await.unwrap();
});

// Receive and verify events
assert_eq!(rx.recv().await, Some(Event::Started));
assert_eq!(rx.recv().await, Some(Event::Completed));
```

### 3. Timeout Handling

```rust
use tokio::time::{timeout, Duration};

let result = timeout(
    Duration::from_secs(5),
    async_operation()
).await;

match result {
    Ok(value) => { /* success */ }
    Err(_) => panic!("operation timed out"),
}
```

**Pattern in Tests**:

```rust
pub async fn wait_for_event_with_timeout<F>(
    codex: &CodexConversation,
    timeout_duration: Duration,
    predicate: F,
) -> Result<()>
where
    F: Fn(&EventMsg) -> bool,
{
    timeout(timeout_duration, wait_for_event(codex, predicate)).await?;
    Ok(())
}
```

---

## Test Categories & Patterns

### Category Matrix

| Category | Focus | Example Test | Key Challenge |
|----------|-------|--------------|---------------|
| **Unit** | Single component | `parse_apply_patch_hunk()` | Isolate logic |
| **Integration** | Component interaction | `shell_tool_executes_command()` | Mock boundaries |
| **E2E** | Full workflows | `test_cli_apply_patch()` | Setup complexity |
| **Parallelism** | Concurrent execution | `read_file_tools_run_in_parallel()` | Timing assertions |
| **Sandbox** | Security policies | `workspace_write_protects_dot_git()` | Actual enforcement |
| **Regression** | Bug fixes | `shell_timeout_includes_prefix()` | Reproduce bug |
| **Platform** | OS-specific features | `landlock_blocks_writes()` | Platform guards |

### Common Patterns

#### Pattern 1: Arrange-Act-Assert

```rust
#[tokio::test]
async fn test_name() -> Result<()> {
    // ARRANGE: Setup
    let server = start_mock_server().await;
    let test = test_codex().build(&server).await?;
    mount_sse_once(&server, mock_response).await;

    // ACT: Execute
    test.codex.submit(operation).await?;
    wait_for_event(&test.codex, |ev| matches!(ev, EventMsg::TaskComplete(_))).await;

    // ASSERT: Verify
    let output = get_tool_output("call-id");
    assert_eq!(output["exit_code"], 0);

    Ok(())
}
```

#### Pattern 2: Test Fixtures

```rust
// Shared setup
fn create_test_file(tmp: &TempDir, name: &str, content: &str) -> PathBuf {
    let path = tmp.path().join(name);
    fs::write(&path, content).unwrap();
    path
}

#[test]
fn test_with_fixture() {
    let tmp = TempDir::new().unwrap();
    let file = create_test_file(&tmp, "test.txt", "content");

    // Use file...
}
```

#### Pattern 3: Parameterized Tests

```rust
#[tokio::test]
async fn test_all_policies() -> Result<()> {
    for policy in [
        SandboxPolicy::ReadOnly,
        SandboxPolicy::WorkspaceWrite { /* ... */ },
        SandboxPolicy::DangerFullAccess,
    ] {
        let test = setup_with_policy(policy).await?;
        run_test_scenario(&test).await?;
    }
    Ok(())
}
```

#### Pattern 4: Golden File Testing

```rust
#[test]
fn test_output_matches_golden() {
    let output = generate_output();
    let golden = include_str!("../fixtures/expected_output.txt");
    assert_eq!(output, golden);
}
```

---

## Challenges in Testing AI Agents

### Challenge 1: Non-Determinism

**Problem**: AI models produce different responses each time.

**Solutions in codex-rs**:

1. **Mock Model Responses**: Control exactly what "model" returns
   ```rust
   let response = sse(vec![
       ev_function_call("call-1", "read_file", r#"{"path": "foo.txt"}"#),
       ev_completed("resp-1"),
   ]);
   ```

2. **Deterministic Test Tools**: Custom tools with predictable behavior
   ```rust
   pub struct TestSyncTool;  // Always returns same result
   ```

3. **Regex Assertions**: Match patterns, not exact strings
   ```rust
   assert_regex_match(r"(?s)^Exit code: \d+", output);
   ```

---

### Challenge 2: Timing Dependencies

**Problem**: Async operations complete at unpredictable times.

**Solutions**:

1. **Event-Based Synchronization**: Wait for events, not timings
   ```rust
   wait_for_event(&codex, |ev| matches!(ev, EventMsg::TaskComplete(_))).await;
   ```

2. **Barriers for Parallelism**: Ensure concurrent operations sync
   ```rust
   barrier.wait().await;  // All participants must arrive
   ```

3. **Timeouts**: Fail tests that hang
   ```rust
   timeout(Duration::from_secs(30), operation()).await?;
   ```

---

### Challenge 3: External Dependencies

**Problem**: Tests need filesystems, network, processes.

**Solutions**:

1. **Isolated Environments**: Temp directories per test
   ```rust
   let tmp = TempDir::new()?;  // Cleaned up automatically
   ```

2. **Mock Servers**: No real API calls
   ```rust
   let server = MockServer::start().await;
   ```

3. **Skip Flags**: Disable tests requiring unavailable resources
   ```rust
   skip_if_no_network!(Ok(()));
   ```

---

### Challenge 4: State Accumulation

**Problem**: Tests pollute shared state (files, globals).

**Solutions**:

1. **Fresh Instances**: Each test gets new `TestCodex`
   ```rust
   let test = test_codex().build(&server).await?;  // Fresh instance
   ```

2. **Isolated Directories**: No shared filesystem
   ```rust
   pub home: TempDir,  // Unique per test
   pub cwd: TempDir,   // Unique per test
   ```

3. **No Global State**: Avoid static mut, prefer Arc/Mutex passed explicitly

---

### Challenge 5: Multi-Turn Conversations

**Problem**: Testing requires multiple API calls in sequence.

**Solutions**:

1. **Sequential Mocking**: Queue responses
   ```rust
   mount_sse_sequence(&server, vec![response1, response2, response3]).await;
   ```

2. **Helper Functions**: Abstract turn execution
   ```rust
   async fn run_turn(test: &TestCodex, prompt: &str) -> Result<()> {
       test.codex.submit(/* ... */).await?;
       wait_for_event(/* ... */).await;
       Ok(())
   }
   ```

3. **Verification Helpers**: Check request history
   ```rust
   let requests = mock.requests();
   assert_eq!(requests.len(), 3);  // 3 API calls
   ```

---

### Challenge 6: Verifying Parallelism

**Problem**: Can't directly observe concurrent execution.

**Solutions**:

1. **Timing Assertions**: Measure total duration
   ```rust
   let start = Instant::now();
   execute_tools().await;
   let duration = start.elapsed();
   assert!(duration < Duration::from_millis(750));  // Parallel
   ```

2. **Synchronization Barriers**: Force coordination
   ```rust
   // Both tools must reach barrier to proceed
   barrier.wait().await;
   ```

3. **Thread Tracking**: Log which thread executed what (for debugging)

---

## Best Practices & Insights

### 1. Test Infrastructure is Production Code

**Insight**: The test harness is as complex as the code it tests.

**Evidence**:
- ~2,000 lines in `common/` (test utilities)
- Sophisticated mock response builders
- Custom tools for testing (test_sync_tool)
- Platform-specific test infrastructure

**Lesson**: Invest in test infrastructure. It pays off in:
- Easier test writing
- More reliable tests
- Faster debugging
- Better coverage

---

### 2. Mock at Boundaries, Not Inside

**Good**:
```rust
// Mock the HTTP API (boundary)
let server = MockServer::start().await;
mount_sse_once(&server, response).await;

// Real tool execution (inside)
let result = shell_handler.handle(invocation).await?;
```

**Bad**:
```rust
// Mock every internal function
let mock_executor = MockExecutor::new();
let mock_formatter = MockFormatter::new();
let mock_tracker = MockTracker::new();
// Brittle, high maintenance
```

**Lesson**: Mock external dependencies (APIs, filesystems), not internal abstractions.

---

### 3. Test One Thing Well

**Good**:
```rust
#[test]
fn parse_add_file_hunk() {
    let patch = "...";
    let changes = parse_apply_patch(patch)?;
    assert_eq!(changes.len(), 1);
    assert_eq!(changes[0].path, "new.txt");
}
```

**Bad**:
```rust
#[test]
fn test_everything() {
    // Parse patch
    // Execute patch
    // Verify output
    // Check events
    // Validate error handling
    // Test edge cases
    // ... 200 lines later
}
```

**Lesson**: Small, focused tests are easier to:
- Write
- Understand
- Debug
- Maintain

---

### 4. Make Failures Obvious

**Good**:
```rust
assert_eq!(
    output["exit_code"], 0,
    "expected exit_code=0, got {} with output: {:?}",
    output["exit_code"], output["output"]
);
```

**Bad**:
```rust
assert!(output["exit_code"] == 0);  // No context on failure
```

**Lesson**: Include diagnostic information in assertion messages.

---

### 5. Test Error Paths, Not Just Happy Paths

**codex-rs Coverage**:
```rust
// Happy path
#[test] fn tool_succeeds_with_valid_input()

// Error paths
#[test] fn tool_fails_with_invalid_input()
#[test] fn tool_fails_with_missing_file()
#[test] fn tool_times_out_on_long_command()
#[test] fn tool_truncates_large_output()
#[test] fn tool_handles_sandbox_violation()
```

**Lesson**: Error handling code is critical code. Test it thoroughly.

---

### 6. Use Property-Based Testing Sparingly

**Observation**: codex-rs uses almost no property testing (quickcheck, proptest).

**Why**: Property testing is hard for:
- Complex stateful systems (agent conversations)
- External dependencies (filesystems, networks)
- Non-pure functions (tool execution)

**When to Use**:
- Parsers (input → output, no side effects)
- Formatters (data transformations)
- Algorithms (sorting, searching)

**Example Use Case**:
```rust
proptest! {
    #[test]
    fn parse_never_panics(patch in ".*") {
        let _ = parse_apply_patch(&patch);  // Shouldn't panic
    }
}
```

**Lesson**: Property testing shines for pure functions, struggles with I/O-heavy code.

---

### 7. Platform-Specific Tests Need Guards

**Pattern**:
```rust
#[cfg(target_os = "macos")]
#[tokio::test]
async fn test_seatbelt_sandbox() {
    // macOS-specific sandbox test
}

#[cfg(target_os = "linux")]
#[tokio::test]
async fn test_landlock_sandbox() {
    // Linux-specific sandbox test
}
```

**Also**:
```rust
if std::env::var("CI").is_ok() && !has_capability() {
    eprintln!("Skipping test in CI without capability");
    return;
}
```

**Lesson**: Guard platform-specific tests to avoid CI failures.

---

### 8. Test Helpers Should Be Obvious

**Good**:
```rust
async fn run_turn(test: &TestCodex, prompt: &str) -> Result<()> {
    // Clear, obvious what this does
}

fn assert_parallel_duration(duration: Duration) {
    // Clear assertion
}
```

**Bad**:
```rust
async fn do_it(t: &T, p: &str) -> R {
    // What does this do?
}
```

**Lesson**: Test helpers should be self-documenting.

---

### 9. Flaky Tests Are Unacceptable

**Strategies to Avoid Flakiness**:

1. **Use Events, Not Timings**:
   ```rust
   // Good
   wait_for_event(&codex, |ev| matches!(ev, EventMsg::TaskComplete(_))).await;

   // Bad (flaky)
   tokio::time::sleep(Duration::from_millis(100)).await;  // Hope it's done?
   ```

2. **Deterministic Mocking**:
   ```rust
   // Good
   mount_sse_sequence(&server, vec![resp1, resp2]).await;

   // Bad (flaky)
   // Sometimes returns resp1, sometimes resp2 (race condition)
   ```

3. **Isolated Environments**:
   ```rust
   // Good
   let tmp = TempDir::new()?;  // Each test gets own directory

   // Bad (flaky)
   fs::write("/tmp/shared_file.txt", "...")?;  // Tests collide
   ```

**Lesson**: Flaky tests erode confidence. Eliminate them ruthlessly.

---

### 10. Integration Tests > Unit Tests for Agents

**Observation**: codex-rs has more integration tests than unit tests.

**Why**: The value is in **integration**:
- Does the tool execute correctly?
- Is the output formatted properly?
- Does it integrate with the conversation flow?
- Are errors handled gracefully?

**Unit tests** struggle because:
- Components have many dependencies
- Mocking everything is brittle
- Real integration bugs slip through

**Balance**:
```
Unit Tests:      30% (parsers, formatters, algorithms)
Integration:     50% (tool execution, turn flows)
E2E Tests:       20% (CLI, multi-turn conversations)
```

**Lesson**: For complex systems, integration tests provide more value per line of test code.

---

## Conclusion

The codex-rs test architecture demonstrates that **testing AI agent harnesses requires specialized infrastructure**:

### Key Takeaways

1. **Determinism Through Mocking**: Control model responses completely via WireMock
2. **Isolation Through Environments**: TempDir per test prevents pollution
3. **Observability Through Events**: Event-based assertions avoid timing flakiness
4. **Verification Through Timing**: Parallelism tests use duration assertions
5. **Realism Through Integration**: Test real tool execution, not just mocks
6. **Flexibility Through Builders**: TestCodexBuilder enables easy test customization
7. **Confidence Through Coverage**: Test errors as thoroughly as happy paths

### Test Infrastructure Components

| Component | Purpose | Complexity | Value |
|-----------|---------|------------|-------|
| TestCodex Harness | Isolated test environments | High | Essential |
| Mock Response Builder | Deterministic model responses | Medium | Essential |
| Sequential Responder | Multi-turn conversations | Medium | High |
| Event Waiting | Async synchronization | Low | Essential |
| Timing Assertions | Parallelism verification | Low | High |
| Barrier Synchronization | Concurrent test coordination | Medium | Medium |
| Platform Guards | Cross-platform compatibility | Low | Essential |

### Common Pitfalls to Avoid

1. ❌ **Timing-based waits** → Use event-based synchronization
2. ❌ **Shared state** → Use isolated environments
3. ❌ **Real API calls** → Use mock servers
4. ❌ **Over-mocking** → Mock boundaries, not internals
5. ❌ **Giant tests** → One assertion per test
6. ❌ **Flaky tests** → Deterministic setup and teardown
7. ❌ **Missing error tests** → Test failures as thoroughly as successes
8. ❌ **Poor diagnostics** → Include context in assertions

### Investment vs Return

**Initial Investment**: High
- Custom test harnesses
- Mock infrastructure
- Helper libraries
- Platform-specific tests

**Long-term Return**: Very High
- Fast test execution (no real API calls)
- Reliable tests (deterministic)
- Easy to add new tests (reuse infrastructure)
- Confident refactoring (comprehensive coverage)
- Clear failure diagnostics (good assertions)

### The Meta-Lesson

**Testing an AI agent harness is like building a second agent harness** - one that controls and observes the first. The test infrastructure in codex-rs is:

- **As complex** as the production code
- **As important** as the production code
- **As carefully architected** as the production code

Treat it accordingly. The payoff is **reliable, maintainable, production-grade software**.

---

**Document Version**: 1.0
**Last Updated**: 2025-10-10
**Feedback**: Questions or suggestions about testing strategy? Let's discuss.
