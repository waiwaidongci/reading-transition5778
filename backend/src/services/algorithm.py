from collections import Counter
import hashlib,json
from .domain_validation import validate_parameters
from .normalization import split_path,fold_path,mapping_of
def calculate(records,parameters,dict_version=None):
    p=validate_parameters(parameters);edges=Counter();outgoing=Counter();incoming=Counter();sessions=set()
    mapping=mapping_of(dict_version) if dict_version is not None else None
    raw_pairs=0;folded_pairs=0
    for r in records:
        v=r['values'];sid=v['session']
        if sid in sessions:raise ValueError('会话编号重复，请将一个完整会话保存在同一行')
        sessions.add(sid)
        parts=split_path(v['path'])
        if mapping:
            path=fold_path(parts,mapping)
        else:
            path=parts
        raw_pairs+=max(0,len(parts)-1)
        folded_pairs+=max(0,len(path)-1)
        # 折叠后连续同章不再产生接续边；接续及全部分母在归一后的路径上重算
        for a,b in zip(path,path[1:]):edges[a,b]+=1;outgoing[a]+=1;incoming[b]+=1
    total=sum(edges.values())
    if total==0:raise ValueError('没有相邻章节转移；单章会话（或归一折叠后）不形成接续边')
    rows=[]
    for (a,b),count in edges.items():
        if count<p['min_count']:continue
        prob=count/outgoing[a];base=incoming[b]/total
        rows.append({'from':a,'to':b,'count':count,'conditional_probability':prob,'target_base_rate':base,'lift':prob/base,'support':count/total})
    rows.sort(key=lambda r:(-r['lift'],-r['count'],r['from'],r['to']));rows=rows[:p['top_n']]
    summary=[{'label':'独立会话','value':len(records)},{'label':'原始相邻对','value':raw_pairs},
             {'label':'折叠后接续边','value':folded_pairs},{'label':'有效接续边','value':total},
             {'label':'达标规则','value':len(rows)},{'label':'章节数','value':len(set(outgoing)|set(incoming))}]
    if mapping is not None:
        summary.insert(1,{'label':'归一词典版本','value':'v'+str(dict_version.version)})
    return {'summary':summary, 'rows':rows,'columns':['from','to','count','conditional_probability','target_base_rate','lift','support'],'chart':[{'label':r['from']+' → '+r['to'],'value':r['lift']} for r in rows[:12]],'target_counts':dict(incoming),'outgoing_counts':dict(outgoing),'explanation':'P(下一章=b | 当前章=a)=边a→b次数/从a出发总次数；目标基率=所有接续边中到达b次数/总边数；提升度=条件概率/目标基率。归一词典把别名链接到终点章节并折叠连续同章，接续与全部分母在归一后的路径上重算；原始路径保留在样本中。无跨会话拼接，无因果推断。','checksum':hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest(),'seed':42}
