import json
import uuid

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from app.agents.product_recommender.chat import recommend_for_chat, wants_product_recommendation
from app.core import db
from app.prompts.prompt_builder import get_prompt

router = APIRouter()


@router.get("/sessions")
async def list_sessions():
    """Sidebar data: id/title/timestamps for every persisted session,
    newest-active first."""
    return await db.list_sessions()


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str, request: Request):
    """Replay a past session's messages so the frontend can hydrate the
    chat window when a user picks it from the sidebar."""
    graph = request.app.state.agent_graph
    return await graph.get_history(session_id)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, request: Request):
    graph = request.app.state.agent_graph
    await db.delete_session(session_id)
    try:
        await graph.graph.checkpointer.adelete_thread(session_id)
    except Exception as e:
        print(f"Error deleting checkpoint state for session {session_id}: {e}")
    return {"deleted": session_id}


@router.websocket("/agents/langgraph")
async def langgraph_websocket(websocket: WebSocket):
    await websocket.accept()

    graph = websocket.app.state.agent_graph

    # The frontend owns session identity - it persists a session_id in
    # localStorage so a chat can be resumed across reconnects, page
    # reloads, and app restarts (see frontend/src/services/api.ts). Fall
    # back to a fresh id for anything that connects without one.
    session_id = websocket.query_params.get("session_id") or f"websocket_{uuid.uuid4().hex[:8]}"

    print(f"WebSocket connection established for session_id: {session_id}")

    # Only greet on a genuinely new session - a resumed one already has its
    # history loaded by the frontend via GET /sessions/{id}/messages, so
    # re-sending the intro here would just duplicate it on every reconnect.
    # `greet=false` lets a client that renders its own empty state (the Geneva
    # chat) skip the intro, so its first reply is always the answer it asked for.
    greet = websocket.query_params.get("greet", "true").lower() not in ("0", "false", "no")
    is_new_session = greet and not await graph.get_history(session_id)
    if is_new_session:
        try:
            await websocket.send_text(json.dumps({
                "message": get_prompt("triage.introduction"),
                "agent_name": "Triage Agent",
                "market_research_response": {"message_result": "", "data": {}},
            }, ensure_ascii=False))
        except Exception as e:
            print(f"Error sending welcome message: {e}")

    try:
        while True:
            try:
                # Use receive() instead of receive_text() to properly handle disconnect messages
                message = await websocket.receive()

                # Check for disconnect message first
                if message["type"] == "websocket.disconnect":
                    print("WebSocket disconnect message received")
                    break

                # Only process text messages
                if message["type"] != "websocket.receive":
                    print(f"Unexpected message type: {message['type']}")
                    continue

                # Get the text data
                data = message.get("text", "")
                print(f"WebSocket received raw data: {repr(data[:100])}")  # Log first 100 chars

                # Skip empty data
                if not data or not data.strip():
                    print("Received empty data, skipping...")
                    continue

                # Try to parse as JSON
                turn_context = None  # Geneva workspace context (role + client), see agents/client_context.py
                try:
                    message_data = json.loads(data)
                    user_message = message_data.get("message", "")
                    turn_context = message_data.get("context")
                except json.JSONDecodeError as e:
                    print(f"JSON decode error: {e}, treating as plain text")
                    # If it's not JSON, treat the entire data as the message
                    user_message = data.strip()

                print(f"Processed message in session {session_id}: '{user_message}'")

                if not user_message:
                    print("No message content found, skipping...")
                    continue

            except WebSocketDisconnect:
                print("WebSocketDisconnect caught during receive")
                break
            except Exception as e:
                error_str = str(e).lower()
                print(f"Error receiving WebSocket data: {e}")

                # Check for the specific disconnect error
                if "cannot call receive once a disconnect message has been received" in error_str:
                    print("Detected disconnect message error - exiting")
                    break

                # Check for other disconnect-related errors
                if any(pattern in error_str for pattern in [
                    "disconnect", "connection closed", "websocket closed"
                ]):
                    print("Connection closed error detected - exiting")
                    break

                continue

            if user_message:
                # Bump the session's position in the sidebar (and title it,
                # the first time round) on any real activity in it.
                try:
                    await db.touch_session(session_id, latest_message=user_message)
                except Exception as e:
                    print(f"Error touching session {session_id}: {e}")

                # PM asking for product recommendations for the client in focus: same RecommendResponse as the REST route.
                if wants_product_recommendation(turn_context, user_message):
                    try:
                        rec = await recommend_for_chat(turn_context["client_id"], websocket.app.state.product_recommender)
                        rec_payload = {
                            "message": f"Product recommendations for client {rec.client_id} are below.",
                            "agent_name": "Product Recommender",
                            "product_recommendation": rec.model_dump(mode="json"),
                            "market_research_response": {"message_result": "", "data": {}},
                        }
                        await websocket.send_text(json.dumps(rec_payload, ensure_ascii=False))
                    except Exception as e:
                        print(f"Error producing product recommendation: {e}")
                        await websocket.send_text(json.dumps({
                            "message": f"I could not produce product recommendations: {str(e)[:200]}",
                            "agent_name": "Product Recommender",
                        }, ensure_ascii=False))
                    continue

                # Process with LangGraph
                try:
                    print(f"Processing message '{user_message}' with session {session_id}")
                    result = await graph.process_message(
                        message=user_message,
                        session_id=session_id,  # Use unique session ID
                        websocket_client=None,  # Don't pass websocket to avoid conflicts
                        context=turn_context,
                    )

                    print(f"Graph result: agent={result.get('agent_name')}, message='{result.get('message', '')[:100]}...'")

                    # Clean the result to ensure JSON serializability
                    def clean_for_json(obj):
                        """Recursively clean object to make it JSON serializable"""
                        if isinstance(obj, dict):
                            return {k: clean_for_json(v) for k, v in obj.items() if v is not None}
                        elif isinstance(obj, list):
                            return [clean_for_json(item) for item in obj]
                        elif isinstance(obj, (str, int, float, bool)):
                            return obj
                        else:
                            return str(obj) if obj is not None else ""

                    # Clean the result
                    result = clean_for_json(result)

                    # Send handoff notification first if available
                    handoff_message = result.get("handoff_message")
                    if handoff_message and handoff_message.strip():
                        handoff_data = {
                            "info_message": str(handoff_message)
                        }
                        try:
                            await websocket.send_text(json.dumps(handoff_data))
                            print(f"Sent handoff message: {handoff_message}")
                        except Exception as e:
                            print(f"Error sending handoff message: {e}")

                    # Send response in the format the frontend expects
                    response_data = {
                        "message": str(result.get("message", "No response generated")),
                        "agent_name": str(result.get("agent_name", "System")),
                        "market_research_response": result.get("market_research_response", {"message_result": "", "data": {}}),
                    }

                    # Ensure all parts are JSON serializable
                    response_data = clean_for_json(response_data)

                    try:
                        await websocket.send_text(json.dumps(response_data, ensure_ascii=False))
                        print(f"Sent response: agent={response_data['agent_name']}")
                    except Exception as e:
                        print(f"Error sending response: {e}")
                        # Send a simple error message
                        simple_response = {
                            "message": "Response generated but couldn't be sent properly",
                            "agent_name": "System",
                        }
                        await websocket.send_text(json.dumps(simple_response))

                except Exception as e:
                    print(f"Error processing message: {e}")
                    import traceback
                    traceback.print_exc()
                    error_response = {
                        "message": "I apologize, but I encountered an error processing your request.",
                        "agent_name": "System",
                    }
                    try:
                        await websocket.send_text(json.dumps(error_response))
                    except Exception as send_error:
                        print(f"Error sending error response: {send_error}")
                        break  # Exit if we can't send error response

    except WebSocketDisconnect:
        print("WebSocket disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        try:
            await websocket.close()
        except Exception as close_error:
            print(f"Error closing websocket: {close_error}")
        print(f"WebSocket session {session_id} ended")
