# Save as app.py
import streamlit as st
import pandas as pd
import networkx as nx
import json
import streamlit.components.v1 as components

st.set_page_config(layout="wide", page_title="Tax Network & UBO Analyzer")

st.title("🕸️ Tax Network & Ultimate Beneficial Owner (UBO) Analyzer")
st.markdown("""
Aplikasi ini mendeteksi struktur kepemilikan berlapis, akumulasi persentase saham, dan menemukan **Ultimate Beneficial Owner (UBO)** seperti Orang Pribadi (OP) atau Perusahaan Luar Negeri (LN) dari entitas Badan Wajib Pajak menggunakan kombinasi **NetworkX** dan **D3.js**.
""")

# Load Data
@st.cache_data
def load_data():
    nodes = pd.read_csv('nodes_masked.csv')
    edges = pd.read_csv('edges_masked.csv')
    return nodes, edges

try:
    nodes_df, edges_df = load_data()
except FileNotFoundError:
    st.error("File 'nodes_masked.csv' dan 'edges_masked.csv' tidak ditemukan. Pastikan kedua file berada di direktori yang sama.")
    st.stop()

# Sidebar for Filters and Search
st.sidebar.header("🔍 Kontrol & Pencarian")
search_query = st.sidebar.text_input("Cari Nama / ID Wajib Pajak:", "").strip()

# Build NetworkX Graph
@st.cache_resource
def build_graph(_nodes, _edges):
    G = nx.DiGraph()
    # Add nodes with attributes
    for _, r in _nodes.iterrows():
        G.add_node(int(r['id']), nama=str(r['nama']), jenis_node=str(r['jenis_node']))
    # Add edges: source owns target
    for _, r in _edges.iterrows():
        G.add_edge(
            int(r['sumber']), 
            int(r['target']), 
            rel_id=int(r['rel_id']),
            persentase=float(r['persentase']), 
            nilai=float(r['nilai']), 
            dividen=float(r['dividen'])
        )
    return G

G = build_graph(nodes_df, edges_df)

# UBO Pathfinding Logic via DFS
def find_ubo_paths(graph, target_node_id):
    """
    Mencari seluruh jalur kepemilikan ke atas (ancestors) untuk menemukan UBO (OP, LN, Non NPWP)
    dan menghitung akumulasi persentase kepemilikan secara multiplikatif sepanjang jalur.
    """
    visited = set()
    paths = []
    
    def dfs(current_node, current_path, current_mult):
        if current_node in visited:
            return  # Mencegah loop/circular reference tak terbatas
        visited.add(current_node)
        
        # Cari siapa yang memiliki current_node (predecessors di dalam directed graph)
        predecessors = list(graph.predecessors(current_node))
        
        if not predecessors:
            # Jika tidak ada yang memiliki di atasnya, berarti ini adalah node puncak (UBO)
            paths.append({
                "path": current_path,
                "multiplier": current_mult,
                "ubo_id": current_node,
                "ubo_nama": graph.nodes[current_node].get('nama', 'Unknown'),
                "ubo_jenis": graph.nodes[current_node].get('jenis_node', 'Unknown')
            })
        else:
            for pred in predecessors:
                edge_data = graph.get_edge_data(pred, current_node)
                pct = edge_data.get('persentase', 0)
                # Normalisasi jika data diinput dalam basis 0-100 persen
                pct_val = pct / 100.0 if pct > 1.0 else pct
                if pct_val <= 0: pct_val = 0.0001
                
                dfs(pred, [pred] + current_path, current_mult * pct_val)
        
        visited.remove(current_node)

    if target_node_id in graph:
        dfs(target_node_id, [target_node_id], 1.0)
    return paths

selected_node_id = None
if search_query:
    matched = nodes_df[nodes_df['nama'].str.contains(search_query, case=False, na=False) | (nodes_df['id'].astype(str) == search_query)]
    if not matched.empty:
        st.sidebar.success(f"Ditemukan {len(matched)} Wajib Pajak.")
        selected_name = st.sidebar.selectbox("Pilih Entitas Spesifik:", matched['nama'].tolist())
        selected_node_id = int(matched[matched['nama'] == selected_name]['id'].values[0])
    else:
        st.sidebar.warning("Wajib Pajak tidak ditemukan.")

# Pembuatan data spesifik jika ada node yang dipilih
if selected_node_id is not None:
    st.subheader(f"📊 Hasil Analisis Jalur UBO untuk: {nodes_df[nodes_df['id'] == selected_node_id]['nama'].values[0]} ({selected_node_id})")
    
    ubo_results = find_ubo_paths(G, selected_node_id)
    
    # Render Tabel Informasi UBO
    ubo_table_data = []
    nodes_to_include = {selected_node_id}
    edges_to_include = set()
    
    for path_info in ubo_results:
        ubo_table_data.append({
            "UBO ID": path_info["ubo_id"],
            "Nama UBO": path_info["ubo_nama"],
            "Jenis UBO": path_info["ubo_jenis"],
            "Akumulasi Kepemilikan (Multiplikatif)": f"{path_info['multiplier'] * 100:.4f}%"
        })
        p = path_info["path"]
        for n in p:
            nodes_to_include.add(n)
        for i in range(len(p) - 1):
            edges_to_include.add((p[i], p[i+1]))
            
    st.dataframe(pd.DataFrame(ubo_table_data), use_container_width=True)
    
    # Sertakan juga anak perusahaan tingkat 1 di bawahnya agar visualisasi lebih kaya kontekstual
    for successor in G.successors(selected_node_id):
        nodes_to_include.add(successor)
        edges_to_include.add((selected_node_id, successor))
        
    # Format JSON untuk D3.js
    d3_nodes = [{"id": str(nid), "nama": G.nodes[nid].get('nama', 'Unknown'), "jenis_node": G.nodes[nid].get('jenis_node', 'Unknown'), "is_target": nid == selected_node_id} for nid in nodes_to_include]
    d3_links = [{"source": str(u), "target": str(v), "persentase": G[u][v].get('persentase', 0), "nilai": G[u][v].get('nilai', 0), "dividen": G[u][v].get('dividen', 0)} for u, v in edges_to_include]
    network_data = {"nodes": d3_nodes, "links": d3_links}
    
else:
    st.info("💡 Masukkan nama atau ID Wajib Pajak di sidebar untuk mendeteksi UBO dan memetakan grafisnya.")
    # Tampilan default awal: Ambil 40 transaksi saham terbesar agar graf tidak kosong saat dibuka
    top_edges = edges_df.nlargest(40, 'nilai')
    sample_node_ids = set(top_edges['sumber'].tolist() + top_edges['target'].tolist())
    
    d3_nodes = [{"id": str(nid), "nama": G.nodes[nid].get('nama', 'Unknown'), "jenis_node": G.nodes[nid].get('jenis_node', 'Unknown'), "is_target": False} for nid in sample_node_ids if nid in G]
    d3_links = [{"source": str(int(r['sumber'])), "target": str(int(r['target'])), "persentase": float(r['persentase']), "nilai": float(r['nilai']), "dividen": float(r['dividen'])} for _, r in top_edges.iterrows()]
    network_data = {"nodes": d3_nodes, "links": d3_links}

json_data_str = json.dumps(network_data)

# Injecting D3.js Inside Streamlit Component
html_template = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        body {{ font-family: sans-serif; margin: 0; background-color: #0e1117; color: #ffffff; overflow: hidden; }}
        #graph-container {{ width: 100vw; height: 600px; background-color: #131722; border-radius: 8px; position: relative; }}
        .node {{ stroke: #22252a; stroke-width: 2px; cursor: pointer; }}
        .node:hover {{ stroke: #fff !important; stroke-width: 3px; }}
        .link {{ stroke: #4f5660; stroke-opacity: 0.6; fill: none; }}
        .label {{ font-size: 11px; fill: #e0e0e0; pointer-events: none; text-shadow: 0px 1px 3px rgba(0,0,0,0.9); }}
        #tooltip {{ position: absolute; background: rgba(20, 24, 33, 0.95); border: 1px solid #3b4252; padding: 10px; border-radius: 5px; font-size: 12px; color: #eceff4; pointer-events: none; visibility: hidden; box-shadow: 0px 4px 12px rgba(0,0,0,0.5); z-index: 10; }}
        .legend {{ position: absolute; top: 15px; left: 15px; background: rgba(30, 34, 42, 0.85); padding: 12px; border-radius: 6px; border: 1px solid #2e3440; font-size: 11px; line-height: 1.6; }}
        .legend-item {{ display: flex; align-items: center; margin-bottom: 4px; }}
        .legend-color {{ width: 12px; height: 12px; border-radius: 50%; margin-right: 8px; }}
    </style>
</head>
<body>
    <div id="graph-container">
        <div class="legend">
            <strong>Kategori Wajib Pajak</strong>
            <div class="legend-item"><div class="legend-color" style="background: #1f77b4;"></div>Badan</div>
            <div class="legend-item"><div class="legend-color" style="background: #2ca02c;"></div>Orang Pribadi (OP)</div>
            <div class="legend-item"><div class="legend-color" style="background: #ff7f0e;"></div>Luar Negeri (LN)</div>
            <div class="legend-item"><div class="legend-color" style="background: #d62728;"></div>Non NPWP</div>
            <div style="border-top: 1px solid #434c5e; margin: 6px 0;"></div>
            <div class="legend-item"><div style="width:16px; height:2px; background:#ebcb4b; margin-right:6px;"></div>Relasi Aktif</div>
        </div>
        <div id="tooltip"></div>
        <svg id="svg-graph" width="100%" height="100%"></svg>
    </div>

    <script>
        const graphData = {json_data_str};
        const width = document.getElementById('graph-container').clientWidth;
        const height = 600;

        const svg = d3.select("#svg-graph").attr("viewBox", [0, 0, width, height]);
        
        // Arrow markers definition
        svg.append("defs").flatMap(d => ['normal', 'highlighted']).forEach(type => {{
            svg.select("defs").append("marker")
                .attr("id", `arrow-${{type}}`)
                .attr("viewBox", "0 -5 10 10")
                .attr("refX", 20).attr("refY", 0)
                .attr("markerWidth", 6).attr("markerHeight", 6)
                .attr("orient", "auto")
                .append("path")
                .attr("fill", type === 'highlighted' ? "#ebcb4b" : "#4f5660")
                .attr("d", "M0,-5L10,0L0,5");
        }});

        const gContainer = svg.append("g");

        svg.call(d3.zoom().scaleExtent([0.1, 4]).on("zoom", (e) => gContainer.attr("transform", e.transform)));

        function getNodeColor(d) {{
            if (d.is_target) return "#bf616a"; 
            switch(d.jenis_node) {{
                case "Badan": return "#1f77b4";
                case "OP": return "#2ca02c";
                case "LN": return "#ff7f0e";
                case "Non NPWP": return "#d62728";
                default: return "#969696";
            }}
        }}

        const simulation = d3.forceSimulation(graphData.nodes)
            .force("link", d3.forceLink(graphData.links).id(d => d.id).distance(140))
            .force("charge", d3.forceManyBody().strength(-350))
            .force("center", d3.forceCenter(width / 2, height / 2))
            .force("collision", d3.forceCollide().radius(40));

        const link = gContainer.append("g").selectAll("path")
            .data(graphData.links).join("path")
            .attr("class", "link")
            .attr("stroke-width", d => Math.max(1.5, Math.min(6, d.persentase / 20)))
            .attr("marker-end", "url(#arrow-normal)");

        const node = gContainer.append("g").selectAll("circle")
            .data(graphData.nodes).join("circle")
            .attr("class", "node")
            .attr("r", d => d.is_target ? 14 : 9)
            .attr("fill", d => getNodeColor(d));

        const label = gContainer.append("g").selectAll("text")
            .data(graphData.nodes).join("text")
            .attr("class", "label").attr("dy", 20).attr("text-anchor", "middle")
            .text(d => d.nama);

        const tooltip = d3.select("#tooltip");

        node.on("mouseover", function(e, d) {{
            tooltip.style("visibility", "visible").html(`<strong>ID:</strong> ${{d.id}}<br/><strong>Nama:</strong> ${{d.nama}}<br/><strong>Jenis:</strong> ${{d.jenis_node}}`);
        }}).on("mousemove", e => tooltip.style("top", (e.pageY - 10) + "px").style("left", (e.pageX + 15) + "px"))
           .on("mouseout", () => tooltip.style("visibility", "hidden"))
           .on("click", function(e, d) {{
                link.style("stroke", l => (l.target.id === d.id || l.source.id === d.id) ? "#ebcb4b" : "#4f5660")
                    .style("stroke-opacity", l => (l.target.id === d.id || l.source.id === d.id) ? 1.0 : 0.2)
                    .attr("marker-end", l => (l.target.id === d.id || l.source.id === d.id) ? "url(#arrow-highlighted)" : "url(#arrow-normal)");
           }});

        link.on("mouseover", function(e, d) {{
            tooltip.style("visibility", "visible").html(`<strong>Saham:</strong> ${{d.persentase}}%<br/><strong>Nilai:</strong> Rp ${{Number(d.nilai).toLocaleString('id-ID')}}<br/><strong>Dividen:</strong> Rp ${{Number(d.dividen).toLocaleString('id-ID')}}`);
        }}).on("mousemove", e => tooltip.style("top", (e.pageY - 10) + "px").style("left", (e.pageX + 15) + "px"))
           .on("mouseout", () => tooltip.style("visibility", "hidden"));

        simulation.on("tick", () => {{
            link.attr("d", d => `M${{d.source.x}},${{d.source.y}} L${{d.target.x}},${{d.target.y}}`);
            node.attr("cx", d => d.x).attr("cy", d => d.y);
            label.attr("x", d => d.x).attr("y", d => d.y);
        }});

        node.call(d3.drag()
            .on("start", (e, d) => {{ if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
            .on("drag", (e, d) => {{ d.fx = e.x; d.fy = e.y; }})
            .on("end", (e, d) => {{ if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }}));
    </script>
</body>
</html>
"""
components.html(html_template, height=620, scrolling=False)
