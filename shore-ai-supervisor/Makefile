PROTO_DIR := proto/shore/supervisor/v1
PB_OUT    := src/shore_supervisor/_pb

.PHONY: proto clean-proto

proto:
	mkdir -p $(PB_OUT)
	touch $(PB_OUT)/__init__.py
	python -m grpc_tools.protoc \
	  -I$(PROTO_DIR) \
	  --python_out=$(PB_OUT) \
	  --grpc_python_out=$(PB_OUT) \
	  $(PROTO_DIR)/*.proto
	for f in $(PB_OUT)/*_pb2_grpc.py; do \
	  sed -i.bak -E 's/^import ([a-zA-Z0-9_]+_pb2)( as |$$)/from . import \1\2/' $$f; \
	  rm -f $$f.bak; \
	done

clean-proto:
	rm -rf $(PB_OUT)
