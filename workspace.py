"""Laptop learning workbench. Learn executes real nodes; Replay never invokes tools."""
from datetime import datetime
import json
import os
from pathlib import Path
import statistics

import requests
import streamlit as st
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from copilot.inspection import current_execution, execution_choices
API = os.getenv("COPILOT_API_URL", "http://127.0.0.1:8529")
RAG = os.getenv("RAG_API_URL", "http://127.0.0.1:8011")
st.set_page_config(page_title="Research Copilot · Node Workbench", page_icon="↳", layout="wide")
en = st.sidebar.selectbox("Language" if st.session_state.get("language-choice", "English") == "English" else "Ngôn ngữ", ["English", "Vietnamese"], key="language-choice") == "English"
t = lambda a, b: a if en else b
st.markdown('''<style>
:root{--color-ink:#163e3b;--color-muted:#617871;--color-paper:#f6f6ee;--color-line:#d2ddd3;--color-accent:#147a63;--font-body:"Segoe UI",sans-serif;--font-code:Consolas,monospace}
.stApp{background:var(--color-paper);font-family:var(--font-body)}
.block-container{padding-top:1.5rem;max-width:1600px}h1,h2,h3{color:var(--color-ink);letter-spacing:-.035em;font-style:normal;overflow-wrap:anywhere}
h1{font-size:2rem}div[data-testid="stMetricValue"]{font-size:24px}
.eyebrow{font:12px var(--font-code);color:var(--color-accent);letter-spacing:.08em}.lede{color:var(--color-muted);max-width:850px}
div[data-testid="stMetric"]{border-top:1px solid var(--color-line);padding-top:12px}
div[data-testid="stJson"]{max-height:420px;overflow:auto}button{white-space:nowrap}
html,body{overflow-x:clip}pre{font-family:var(--font-code)}
@media(max-width:768px){.block-container{padding:1rem}.stButton button{font-size:12px}}
</style>''', unsafe_allow_html=True)


def api(path, method="GET", payload=None):
    response = requests.request(method, API + path, headers={"Authorization": "Bearer " + st.session_state.get("token", "")}, json=payload, timeout=12)
    if not response.ok:
        try:
            raise ValueError(response.json().get("detail", response.text))
        except json.JSONDecodeError:
            raise ValueError("Service unavailable: " + str(response.status_code))
    return response.json()


st.sidebar.markdown("### " + t("Local demo identity", "Danh tính demo local"))
username = st.sidebar.selectbox(t("Account", "Tài khoản"), ["researcher", "reviewer", "outsider"])
password = st.sidebar.text_input(t("Demo password", "Mật khẩu demo"), value="learn-local-only", type="password")
if st.sidebar.button(t("Sign in", "Đăng nhập"), width='stretch'):
    try:
        r = api("/login", "POST", {"username": username, "password": password})
        st.session_state["token"], st.session_state["user"] = r["token"], r["user"]
        st.rerun()
    except Exception as exc:
        st.sidebar.error(str(exc))
user = st.session_state.get("user")
st.sidebar.caption(t("Development login, not enterprise SSO. The backend supplies roles; the model cannot grant them.", "Đăng nhập phát triển, không phải SSO doanh nghiệp. Role do backend cấp, model không có quyền thay đổi."))
if user:
    st.sidebar.success(f'{user["sub"]} · {user["role"]} · {user["workspace"]}')
st.markdown('<div class="eyebrow">RESEARCH COPILOT / EXECUTION WORKBENCH</div>', unsafe_allow_html=True)
st.title(t("From a question to an approved report.", "Từ câu hỏi đến báo cáo đã được duyệt."))
st.markdown('<p class="lede">'+t("Execute one node. Inspect its data. Understand the next decision. A saved report is the result of evidence, calculation and explicit reviewer approval.", "Chạy một node, xem dữ liệu và hiểu quyết định kế tiếp. Báo cáo chỉ được lưu sau khi có bằng chứng, kết quả tính và reviewer duyệt nội dung.")+'</p>', unsafe_allow_html=True)
workspace, data_tab, experiments, monitoring, guide = st.tabs([t("01 · Workspace", "01 · Thực hành"), t("02 · Data → index", "02 · Data → index"), t("03 · Experiments", "03 · Thí nghiệm"), t("04 · Monitoring", "04 · Theo dõi"), t("05 · Learn A–Z", "05 · Học A–Z")])

with workspace:
    mode = st.radio(t("Execution mode", "Chế độ thực thi"), ["Learn", "Run", "Replay"], horizontal=True)
    if mode == "Replay":
        replay_path = ROOT / "artifacts/replay.json"
        if replay_path.exists():
            replay = json.loads(replay_path.read_text(encoding="utf-8"))
            st.info(t("RECORDED REPLAY — no model calls or tool execution.", "REPLAY ĐÃ LƯU — không gọi model hay thực thi tool."))
            i = st.slider(t("Recorded node", "Node đã ghi"), 0, len(replay["events"]) - 1)
            e = replay["events"][i]
            st.subheader(e["node"])
            left, right = st.columns(2)
            left.json(e["input"])
            right.json(e["output"])
        else:
            st.info("A verified live run will populate artifacts/replay.json.")
    elif not user:
        st.info(t("Sign in as researcher to begin. Switch to reviewer when the draft needs approval.", "Đăng nhập researcher để bắt đầu. Chuyển reviewer khi cần duyệt bản nháp."))
    else:
        with st.expander(t("Create a real request", "Tạo request chạy thật"), expanded=not st.session_state.get("run_id")):
            request = st.text_area(t("Request", "Yêu cầu"), "Find how RRF combines rankings in source rrf, calculate 1/(60+1) + 1/(60+3), and save a short research report.", height=85)
            strategy = st.selectbox(t("Orchestrator", "Cách điều phối"), ["langgraph", "function_loop", "workflow"])
            if st.button(t("Create run", "Tạo lượt chạy"), type="primary"):
                try:
                    st.session_state["run_id"] = api("/runs", "POST", {"request": request, "strategy": strategy})["id"]
                    st.session_state.pop("selected_node", None)
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        try:
            if st.button(t("Refresh run list", "Làm mới danh sách")):
                st.rerun()
            rows = api("/runs")
            choices = [r["id"] for r in rows]
            if choices:
                current = st.session_state.get("run_id")
                chosen = st.selectbox(t("Open a run", "Mở lượt chạy"), choices, index=choices.index(current) if current in choices else 0,
                      format_func=lambda rid: next(r["request"][:65] + " · " + rid[:8] for r in rows if r["id"] == rid))
                st.session_state["run_id"] = chosen
        except Exception as exc:
            st.error(str(exc))

        @st.fragment(run_every="1s")
        def execution_panel():
            rid = st.session_state.get("run_id")
            if not rid:
                return
            follow_key = "follow-latest-" + rid
            selected_key = "selected-node-" + rid
            if st.session_state.pop("reset-inspection-" + rid, False):
                st.session_state[follow_key] = True
                st.session_state[selected_key] = None
            try:
                r = api("/runs/" + rid)
            except Exception as exc:
                st.error(str(exc)); return
            state = r["state"]
            cols = st.columns([2, 2, 2, 3])
            display_status = {"awaiting_approval":t("Needs review","Cần duyệt"),"running":t("Running","Đang chạy"),"paused":t("Paused","Đã dừng"),"completed":t("Completed","Hoàn tất"),"new":t("Ready","Sẵn sàng"),"error":t("Error","Có lỗi"),"recoverable":t("Recoverable","Có thể tiếp tục")}
            cols[0].metric(t("Status", "Trạng thái"), display_status.get(r["status"],r["status"]))
            cols[1].metric(t("Next node", "Node kế tiếp"), state.get("next_node", "understand"))
            cols[2].metric(t("Tool rounds", "Lượt gọi tool"), state.get("rounds", 0))
            cols[3].caption("RUN ID\n\n" + rid)
            busy = r["status"] == "running"
            if busy:
                st.info(t("Executing real work. Inputs and completed node outputs remain inspectable below.", "Đang thực thi thật. Bạn vẫn xem được input và output của các node đã xong bên dưới."))
            if r["status"] not in ("completed", "awaiting_approval"):
                if st.button(t("Execute next node →", "Chạy node tiếp →") if mode == "Learn" else t("Run until approval →", "Chạy đến bước duyệt →"), disabled=busy or user["sub"] != r["owner"], type="primary", key="advance"):
                    try:
                        api(f"/runs/{rid}/advance", "POST", {"continuous": mode == "Run"})
                        st.session_state["reset-inspection-" + rid] = True
                        st.rerun(scope="fragment")
                    except Exception as exc:
                        st.error(str(exc))
            if state.get("error"):
                st.error(state["error"])
            events = r["events"]
            node_names = ["understand", "planner", "tools", "draft", "approval", "save", "finish"]
            node_labels = [t("01 Input", "01 Input"), t("02 Plan", "02 Plan"), t("03 Tools", "03 Tools"), t("04 Draft", "04 Nháp"), t("05 Review", "05 Duyệt"), t("06 Save", "06 Lưu"), t("07 Finish", "07 Xong")]
            for c, name, label in zip(st.columns(7), node_names, node_labels):
                count = sum(e["node"] == name for e in events)
                if c.button(label, key="node-" + name, width='stretch'):
                    st.session_state[selected_key] = name
                    st.session_state[follow_key] = False
                c.caption(str(count) + t(" executions", " lần chạy"))
            st.caption(t("Node buttons inspect history. Execute next node runs the workflow and follows its new result.", "Các nút node dùng để xem lại lịch sử. Chạy node tiếp mới thực thi workflow và hiện kết quả vừa chạy."))
            follow = st.toggle(t("Follow latest execution", "Theo kết quả mới nhất"), value=True, key=follow_key)
            chosen = st.session_state.get(selected_key)
            available = execution_choices(events, chosen)
            history_id = None
            if not follow and available:
                history_id = st.selectbox(t("Execution history", "Lịch sử thực thi"), [e["id"] for e in available],
                    index=len(available)-1, key="history-"+rid+"-"+str(chosen),
                    format_func=lambda eid: next(f'#{events.index(e)+1} · {e["node"]}'+(' → '+e['input']['action'] if e['input'].get('action') else '') for e in available if e['id']==eid))
            event = current_execution(events, follow, chosen, history_id)
            if event is not None:
                if not follow and event["id"] != events[-1]["id"]:
                    st.info(t("Viewing history. The workflow has advanced beyond this execution. Turn on Follow latest execution to see the current result.", "Bạn đang xem lịch sử. Workflow đã chạy qua bước này. Bật Theo kết quả mới nhất để xem kết quả hiện tại."))
                number = next(i for i,e in enumerate(events,1) if e["id"] == event["id"])
                action = event["input"].get("action") or event["output"].get("action")
                st.subheader(f'#{number} · '+event["node"]+(' → '+action if action else '')+" · " + f'{event["elapsed_ms"]:,.0f} ms')
                explanations = {
                    "understand": t("The model translated your request into a validated task spec. It did not grant permissions or run tools.", "Model chuyển câu hỏi thành task spec đã kiểm tra schema. Nó chưa cấp quyền hay chạy tool."),
                    "planner": t("The model proposed the next action. The executor will run only one dependency-safe, allowlisted action.", "Model đề xuất hành động tiếp. Executor chỉ chạy một hành động đúng thứ tự phụ thuộc và có trong allowlist."),
                    "tools": t("Actual MCP output. Search uses only authorized chunks; arithmetic comes from the bounded calculator.", "Đầu ra MCP thật. Search chỉ dùng chunk được phép; phép tính lấy từ calculator có giới hạn."),
                    "draft": t("A draft is not a saved report. The content and destination now have a hash for exact approval.", "Bản nháp chưa phải báo cáo đã lưu. Nội dung và đích lưu có hash để duyệt đúng bản."),
                    "approval": t("This pause is enforced by code. Only an authenticated reviewer in this workspace can decide.", "Việc dừng do code thực thi. Chỉ reviewer đã xác thực cùng workspace mới được quyết định."),
                    "save": t("The canonical report is committed once in SQLite. Markdown is a recoverable export of that record.", "Báo cáo chuẩn chỉ ghi một lần trong SQLite. Markdown là bản xuất có thể tạo lại từ bản ghi đó."),
                    "finish": t("The final answer reports what actually happened, including a rejection or missing evidence.", "Câu trả lời cuối phản ánh việc đã xảy ra, kể cả bị từ chối hay thiếu bằng chứng.")}
                st.caption(explanations[event["node"]])
                observations = event["output"].get("observations", [])
                if observations and observations[-1].get("evidence"):
                    st.dataframe([{ "chunk": e["chunk_id"], "source": e["source_id"], "section": e["section"],
                                    "evidence": e["text"][:240], "rerank_score": e.get("rerank_score") } for e in observations[-1]["evidence"]], hide_index=True, width='stretch')
                left, right = st.columns(2)
                left.markdown("**" + t("INPUT · known before execution", "INPUT · đã biết trước khi chạy") + "**")
                left.json(event["input"], expanded=2)
                right.markdown("**" + t("OUTPUT · actually returned", "OUTPUT · kết quả thực tế") + "**")
                right.json(event["output"], expanded=2)
                observations = event["output"].get("observations", [])
                if observations and observations[-1].get("trace"):
                    trace = observations[-1]["trace"]
                    with st.expander(t("Inspect dense → BM25 → RRF → rerank → evidence gate", "Xem dense → BM25 → RRF → rerank → evidence gate"), expanded=True):
                        l, rr = st.columns(2)
                        l.json({k: trace.get(k) for k in ("authorized_candidates", "dense", "bm25")}, expanded=2)
                        rr.json({k: trace.get(k) for k in ("fusion", "reranked", "gate_threshold", "gate_passed")}, expanded=2)
            elif chosen:
                st.info(t("This node has not executed yet.", "Node này chưa thực thi."))
            if r.get("draft"):
                st.subheader(t("Exact report draft", "Nội dung báo cáo cần duyệt"))
                st.caption("SHA-256 · " + r["draft"]["hash"])
                with st.container(height=280, border=True):
                    st.markdown(r["draft"]["content"])
                if r["status"] == "awaiting_approval":
                    if user["role"] == "reviewer":
                        approve, reject = st.columns(2)
                        for col, approved, label in [(approve, True, t("Approve this exact draft", "Duyệt đúng bản này")), (reject, False, t("Reject — do not save", "Từ chối — không lưu"))]:
                            if col.button(label, key="decision-"+str(approved), type="primary" if approved else "secondary"):
                                try:
                                    api(f"/runs/{rid}/approval", "POST", {"draft_hash": r["draft"]["hash"], "approved": approved, "continuous": True})
                                    st.session_state["reset-inspection-" + rid] = True
                                    st.rerun(scope="fragment")
                                except Exception as exc:
                                    st.error(str(exc))
                    else:
                        st.warning(t("Switch to the reviewer account to approve or reject. Researcher credentials cannot approve a write.", "Chuyển sang reviewer để duyệt/từ chối. Tài khoản researcher không thể duyệt ghi."))
                        with st.expander(t("Edit pending draft · invalidates previous approval", "Sửa bản nháp · hủy approval cũ")):
                            content = st.text_area(t("Edited content", "Nội dung sửa"), r["draft"]["content"], key="edited-"+r["draft"]["hash"])
                            if st.button(t("Update draft", "Cập nhật bản nháp")):
                                try:
                                    api(f"/runs/{rid}/draft", "PATCH", {"title": r["draft"]["title"], "content": content})
                                    st.rerun(scope="fragment")
                                except Exception as exc:
                                    st.error(str(exc))
            if state.get("answer") and r["status"] == "completed":
                st.success(state["answer"])
            if state.get("saved"):
                st.download_button(t("Download saved Markdown", "Tải báo cáo Markdown"), state["saved"]["content"], file_name=state["saved"]["report_id"]+".md")
            st.download_button(t("Export execution trace JSON", "Tải trace JSON"), json.dumps(r, ensure_ascii=False, indent=2), file_name="trace-"+rid+".json")
        execution_panel()

with data_tab:
    st.subheader(t("Ingestion happens before a user request.", "Ingest diễn ra trước khi có request."))
    st.code("Official source → cleaned snapshot → chunks + ACL → embeddings → FAISS index", language=None)
    manifest_path = ROOT.parent / "RAG_project/research-manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        a,b,c = st.columns(3)
        a.metric(t("Official documents", "Tài liệu chính thức"), len(manifest["official_sources"]))
        b.metric(t("Indexed chunks", "Chunk đã index"), manifest["chunks"])
        c.metric(t("Synthetic ACL / attack fixtures", "Fixture ACL / tấn công giả lập"), manifest["synthetic_documents"])
        st.dataframe([{k:v for k,v in s.items() if k in ("source_id", "url", "characters", "chunks", "content_sha256")} for s in manifest["official_sources"]], hide_index=True, width='stretch')
        st.caption(manifest["notice"])
        if user:
            response = requests.get(RAG+"/research/data", headers={"Authorization":"Bearer "+st.session_state["token"]}, timeout=10)
            if response.ok:
                chunks = response.json()["chunks"]
                selected = st.selectbox(t("Inspect an authorized chunk", "Xem chunk được phép"), list(range(len(chunks))), format_func=lambda i:f'{chunks[i]["chunk_id"]} · {chunks[i]["source_id"]} · {chunks[i]["section"][:60]}')
                st.json(chunks[selected])
                st.caption(t("384-dimensional normalized embedding; actual index metadata, not an illustration.", "Embedding chuẩn hóa 384 chiều; metadata index thật, không phải minh họa."))
    else:
        st.info("Run RAG_project/scripts/ingest_research.py to create the corpus.")

with experiments:
    st.subheader(t("Compare orchestration, not framework slogans.", "So sánh thực nghiệm, không dựa vào tên framework."))
    for title, path in [("Orchestration benchmark", ROOT / "artifacts/benchmark.json"), ("Retrieval ablation", ROOT.parent / "RAG_project/research-evaluation.json")]:
        st.markdown("### " + title)
        if path.exists():
            report = json.loads(path.read_text(encoding="utf-8"))
            if "summary" in report:
                st.dataframe(report["summary"], hide_index=True, width='stretch')
            with st.expander(t("Inspect measured report", "Xem report thực tế")):
                st.json(report, expanded=2)
        else:
            st.info(t("No completed experiment report yet. Results will not be invented.", "Chưa có report hoàn tất; không điền số giả."))

with monitoring:
    st.subheader(t("Local executions, measured as they happen.", "Các lần chạy local, đo từ thực tế."))
    if user:
        try:
            m=api('/monitoring');runs=m['runs'];events=m['events'];calls=m['calls']
            a,b,c=st.columns(3)
            a.metric('Runs',len(runs));b.metric('Completed',sum(r['status']=='completed' for r in runs));c.metric('Estimated API cost',f"${sum(x['cost'] if x['cost'] is not None else x['reserved'] for x in calls):.4f}")
            if m.get('metrics'):
                st.dataframe([{'metric': k, 'value': v} for k,v in m['metrics'].items()],hide_index=True,width='stretch')
            times={}
            for e in events: times.setdefault(e['node'],[]).append(e['elapsed_ms'])
            st.dataframe([{'node':k,'executions':len(v),'p95_ms':sorted(v)[max(0,int(.95*(len(v)-1)))]} for k,v in times.items()],hide_index=True,width='stretch')
            st.dataframe([{k:v for k,v in r.items() if k!='state'} for r in runs],hide_index=True,width='stretch')
            st.caption(t('API cost uses conservative peak pricing; unresolved calls keep their reservation. These are local runs, not production traffic or drift detection.', 'Chi phí dùng giá peak bảo thủ; lời gọi chưa rõ kết quả vẫn giữ dự trù. Đây là chạy local, không phải production hay phát hiện drift.'))
        except Exception as exc: st.error(str(exc))

with guide:
    st.subheader(t("Learn by predicting each node’s output.", "Học bằng cách đoán output trước khi chạy node."))
    steps=[('Data','Why is chunking done before the request, while query embedding happens during it?','Vì sao chunk tài liệu trước request, còn embedding câu hỏi chạy khi nhận request?'),('Retrieval','Where do dense and sparse rankings disagree? Calculate one RRF contribution.','Dense và BM25 khác thứ tự ở đâu? Tự tính một số hạng RRF.'),('Permissions','Can the planner change your workspace or approve its own write?','Planner có đổi workspace hay tự duyệt thao tác ghi được không?'),('Evidence','What changes when the question has no supporting passage?','Nếu không có đoạn nào chứa thông tin cần tìm thì hệ thống làm gì?'),('Approval','Change the draft after reviewing its hash. Should the old approval work?','Sửa draft sau khi đã xem hash. Approval cũ còn hợp lệ không?'),('Recovery','Restart while waiting for review; retry save after a commit/export crash.','Restart lúc chờ duyệt; thử lưu lại sau lỗi giữa commit và export.'),('Experiment','When is the fixed workflow cheaper and sufficient?','Khi nào workflow cố định rẻ hơn và đã đủ dùng?')]
    for name,question,vi in steps:
        with st.expander(name): st.write(t(question,vi))
    st.caption(t("Read LEARNING-GUIDE.md for the full walkthrough. Keep answers and observed outputs in LEARNING-JOURNAL.txt.", "Đọc LEARNING-GUIDE.md để đi hết bài. Ghi câu trả lời và output quan sát được vào LEARNING-JOURNAL.txt."))
