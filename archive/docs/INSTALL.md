# FAIRifier Installation Guide

## 🎯 Quick Installation

### Option 1: Minimal Installation (No Dependencies)
```bash
# Download just the main script
wget https://raw.githubusercontent.com/your-repo/fairifier/main/fairifier_final.py

# Run immediately (works with text files)
python fairifier_final.py your_document.txt
```

### Option 2: Full Installation (Recommended)
```bash
# Download all files
git clone https://github.com/your-repo/fairifier.git
cd fairifier

# Install dependencies
pip install -r requirements_final.txt

# Test installation
python fairifier_final.py soil_metagenomics_paper.txt
```

### Option 3: Docker (Coming Soon)
```bash
docker run -v $(pwd):/data fairifier:latest /data/your_document.pdf
```

## 📦 Dependencies Explained

| Package | Purpose | Required? | Fallback |
|---------|---------|-----------|----------|
| `requests` | FAIR Data Station API | No | Local knowledge only |
| `PyMuPDF` | PDF processing | No | Text files only |
| `rdflib` | RDF generation | No | Skip RDF output |
| `PyYAML` | Better YAML formatting | No | Basic YAML |

## 🧪 Verify Installation

```bash
# Test basic functionality
python fairifier_final.py --version

# Test with sample document
echo "Title: Test Document\nAuthors: John Doe\nKeywords: test, demo" > test.txt
python fairifier_final.py test.txt

# Check output
ls output/
```

## 🔧 Troubleshooting

### Common Issues

#### 1. "No module named 'fitz'"
```bash
pip install PyMuPDF
# Or process text files only
```

#### 2. "requests module not found"
```bash
pip install requests
# Or use --no-fair-ds flag
```

#### 3. Permission errors on Windows
```bash
python -m pip install --user -r requirements_final.txt
```

## 🚀 Ready to Use!

Your FAIRifier installation is complete. Start processing documents:

```bash
python fairifier_final.py your_research_paper.pdf
```
