PROTO_DIR := proto/shore/ai/v1
PB_OUT    := src/shore_ai/_pb
PYTHON    ?= python

.PHONY: proto clean-proto

# Flat output layout: all stubs sit directly under _pb/.
# grpc-tools generates `_grpc.py` files with absolute `import xxx_pb2` which
# breaks when the package is nested. The sed step rewrites them to relative
# imports so `from shore_ai._pb import stt_pb2_grpc` works.
proto:
	mkdir -p $(PB_OUT)
	touch $(PB_OUT)/__init__.py
	$(PYTHON) -m grpc_tools.protoc \
	  -I$(PROTO_DIR) \
	  --python_out=$(PB_OUT) \
	  --grpc_python_out=$(PB_OUT) \
	  $(PROTO_DIR)/*.proto
	# Rewrite `import xxx_pb2` -> `from . import xxx_pb2` inside _grpc.py files.
	for f in $(PB_OUT)/*_pb2_grpc.py; do \
	  sed -i.bak -E 's/^import ([a-zA-Z0-9_]+_pb2)( as |$$)/from . import \1\2/' $$f; \
	  rm -f $$f.bak; \
	done

clean-proto:
	rm -rf $(PB_OUT)
