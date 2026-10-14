const charts = [
 ['chart1','charts/01_everyday_choropleth.json'],
 ['chart2','charts/02_category_heatmap.json'],
 ['chart3','charts/03_parcel_boxplot.json'],
 ['chart4','charts/04_rank_slopegraph.json'],
 ['chart5','charts/05_per_capita_lollipop.json'],
 ['chart6','charts/06_bivariate_map.json'],
 ['chart7','charts/07_catchment_choropleth.json'],
 ['chart8','charts/08_quantity_vs_access.json'],
 ['chart9','charts/09_proportional_symbols.json'],
 ['chart10','charts/10_category_share.json'],
 ['chart11','charts/11_broad_vs_everyday.json'],
 ['chart12','charts/12_playground_points.json'],
 ['chart13','charts/13_local_catchment_overlay.json']
];
async function draw([id,url]){
 const el=document.getElementById(id);if(!el)return;
 try{const response=await fetch(url);if(!response.ok)throw Error(`${response.status} ${url}`);const spec=await response.json();await vegaEmbed(el,spec,{actions:{export:true,source:true,compiled:false,editor:true},renderer:'svg'});}
 catch(e){console.error(e);el.innerHTML=`<div class="error">Could not load chart: ${String(e.message).replace(/</g,'&lt;')}. Check data/processed and browser console (F12).</div>`;}
}
window.addEventListener('load',()=>charts.forEach(draw));
