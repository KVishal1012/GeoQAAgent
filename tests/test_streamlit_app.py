import streamlit_app


def test_streamlit_app_exposes_core_functions():
    assert callable(streamlit_app.run_uploaded_dataset)
    assert callable(streamlit_app.generate_agent_draft)
    assert callable(streamlit_app.render_app)

