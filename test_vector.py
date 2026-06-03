from fastembed import TextEmbedding
print("fastembed imported OK")
model = TextEmbedding(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
print("model loaded OK")
result = list(model.embed(["测试文本"]))
print("encode OK, shape:", result[0].shape)
