PROTO_AI := ../shore-ai-service/proto/shore/ai/v1
PROTO_SV := ../shore-ai-supervisor/proto/shore/supervisor/v1
PB_OUT   := app/services/ai_client/_pb

.PHONY: proto clean-proto

# Flat layout + sed postprocess for relative imports (see shore-ai-service
# Makefile for full explanation).
proto:
	mkdir -p $(PB_OUT)
	touch $(PB_OUT)/__init__.py
	python -m grpc_tools.protoc -I$(PROTO_AI) \
	  --python_out=$(PB_OUT) --grpc_python_out=$(PB_OUT) \
	  $(PROTO_AI)/*.proto
	python -m grpc_tools.protoc -I$(PROTO_SV) \
	  --python_out=$(PB_OUT) --grpc_python_out=$(PB_OUT) \
	  $(PROTO_SV)/*.proto
	for f in $(PB_OUT)/*_pb2_grpc.py; do \
	  sed -i.bak -E 's/^import ([a-zA-Z0-9_]+_pb2)( as |$$)/from . import \1\2/' $$f; \
	  rm -f $$f.bak; \
	done

clean-proto:
	rm -rf $(PB_OUT)
