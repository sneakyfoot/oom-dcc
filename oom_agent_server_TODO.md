# OOM Agent Server - Implementation TODO

## ✅ Completed

### Core Infrastructure
- [x] Directory structure setup (`src/oom_agent/`)
- [x] JSON-RPC 2.0 protocol handler (`protocol.py`)
- [x] Session management (`session_manager.py`, `session.py`)
- [x] Scene management endpoints (`scene.py`)
- [x] Hython execution with sandboxing (`execution.py`)
- [x] Guardrails system (`guardrails.py`)
- [x] Image pipeline (`image_pipeline.py`)
- [x] OomContext integration (`context.py`)
- [x] Logging configuration (`logging_config.py`)
- [x] FastAPI app setup (`server.py`)
- [x] Nix integration (`nix/server.nix`, `nix/python-env.nix`)

### Endpoints
- [x] `agent.create_session` - Create session with project/sequence/shot
- [x] `agent.destroy_session` - Clean up session
- [x] `agent.get_status` - Query session status
- [x] `scene.load` - Load HIP file
- [x] `scene.save` - Save scene
- [x] `scene.get_current` - Get current scene info
- [x] `agent.execute` - Run hython code (sandboxed)

### Tools Placeholders
- [x] `tools.farm_submit` - Placeholder for farm submission
- [x] `tools.publish_output` - Placeholder for publish operations
- [x] `tools.cache_refresh` - Placeholder for cache operations

## 🚧 Needs Implementation

### Session & Scene
- [ ] **Houdini initialization integration** - Ensure `oom_hou.py` is properly used instead of direct `import hou`
- [ ] **Session persistence** - Consider file-based or Redis for session recovery
- [ ] **Scene auto-load** - Option to load last saved scene on session start

### Execution
- [ ] **Rich execution output** - Better formatted results for complex data structures
- [ ] **Code validation** - More comprehensive security checks
- [ ] **Async execution pool** - For parallel code execution if needed

### Guardrails
- [ ] **Version auto-increment** - Integrate with `oom_cache` for version management
- [ ] **Path validation** - More comprehensive path checking for your project structure
- [ ] **Resource limits** - CPU/memory/time quotas per session

### Image Pipeline
- [ ] **Screenshot capture** - HDA integration for viewport screenshots
- [ ] **Image compression** - Handle large images efficiently
- [ ] **Image thumbnail generation** - Create preview thumbnails
- [ ] **Delete image endpoint** - `agent.delete_image(session_id, image_path)`

### Context Integration
- [ ] **Full oom_context implementation** - Complete ShotGrid/SGTK bootstrap
- [ ] **Context caching** - Avoid re-fetching from SG for same project/sequence/shot
- [ ] **Entity validation** - Verify project/sequence/shot exist before session creation

### Tool Wrappers
- [ ] **Farm submission** - Integrate with `oom_houdini.submit_pdg_cook`
- [ ] **Publish operations** - Integrate with `oom_cache` or `oom_lop_publish`
- [ ] **Cache management** - Integrate cache refresh/invalidation logic

### Nix/Deployment
- [ ] **Container entrypoint** - Update `houdiniContainerImage` to run `agent-server`
- [ ] **Environment config** - Add env vars for port, host, logging level
- [ ] **Resource limits** - Define CPU/memory limits for agent pods
- [ ] **Health check** - Define Kubernetes liveness/readiness probes

### Testing
- [ ] **Unit tests** - Test protocol parsing, session management
- [ ] **Integration tests** - Test full workflow with Houdini
- [ ] **Load testing** - Validate performance characteristics

## 📋 Future Enhancements (Nice to Have)

1. **WebSocket support** - Real-time bidirectional communication
2. **Command history** - Track and replay agent actions
3. **Session audit logs** - Full audit trail for compliance
4. **Multi-session support** - Handle multiple agents per pod
5. **Hot reload** - Code execution without session restart
6. **Plugin system** - Allow custom tool registration
7. **OpenTelemetry integration** - Add tracing as planned
8. **Rate limiting** - Protect against abuse
9. **GraphQL API** - Alternative to JSON-RPC
10. **SDK clients** - Python/JS clients for easy agent integration

## 🔧 Immediate Next Steps

To complete basic agent deployment:

1. **Update container entrypoint**:
   ```nix
   # In nix/houdini.nix
   config.Entrypoint = [ "${agentServer.agentServer}/bin/agent-server" ];
   ```

2. **Implement HDA for screenshots**:
   - Create HDA that saves viewport to `/tmp/{session_id}/images/`
   - Standardize screenshot format and naming

3. **Add full oom_context bootstrap**:
   - Replace simplified context.py with full ShotGrid integration
   - Add entity validation logic

4. **Test with sample agent**:
   - Create a simple test agent script
   - Verify session creation → scene load → execute workflow
