import numpy as np
from sklearn.neighbors import KernelDensity
from scipy.stats import gaussian_kde
import contourpy
from scipy.fft import rfft2,irfft2,next_fast_len
from scipy.ndimage import fourier_gaussian,map_coordinates
from .statistics import finite

def kde1(a,field='',points=128):
    v=finite(a)
    tolerance=32*np.finfo(float).eps*max(1.,float(np.max(abs(v)))) if len(v) else 0
    if len(v)<2 or np.ptp(v)<=tolerance:return {'kind':'point_mass','x':[float(np.median(v))] if len(v) else [],'density':[1.] if len(v) else [],'n':len(v),'numerical_tolerance':tolerance}
    h=float(np.std(v,ddof=1)*len(v)**(-1/5))
    lo,hi=v.min()-3*h,v.max()+3*h
    if field.endswith('_frac'):lo,hi=max(0,lo),min(1,hi)
    if field.endswith('_pct'):lo,hi=max(0,lo),min(100,hi)
    xs=np.linspace(lo,hi,points)
    # All records fitted. Tree evaluation has explicit numerical tolerances; no sampling.
    unique,weights=np.unique(v,return_counts=True)
    ys=np.zeros(len(xs))
    for start in range(0,len(unique),4096):
        delta=(xs[:,None]-unique[None,start:start+4096])/h
        ys+=np.exp(-.5*delta*delta)@weights[start:start+4096]
    ys/=len(v)*h*np.sqrt(2*np.pi)
    return {'kind':'gaussian_kde','x':xs.tolist(),'density':ys.tolist(),'n':len(v),'bandwidth':h,'rule':'Scott','evaluation':'all-record Gaussian sum; duplicate values weighted exactly','bounded_display':field.endswith(('_frac','_pct'))}

def _fft_evaluator(points):
    """Evaluate the fitted Gaussian mixture on a fine grid; no records are subsampled.

    Bilinear deposition and interpolation are numerical quadrature, independently checked
    against the original all-point KDE at deterministic grid and peak locations.
    """
    lo=points.min(0)-8;hi=points.max(0)+8
    shape=[min(2048,next_fast_len(max(64,int(np.ceil((hi[j]-lo[j])/.04))+1))) for j in range(2)]
    step=(hi-lo)/(np.array(shape)-1);u=(points-lo)/step;base=np.floor(u).astype(int);frac=u-base
    mass=np.zeros((shape[1],shape[0]),float)
    for dx in [0,1]:
        for dy in [0,1]:
            w=(frac[:,0] if dx else 1-frac[:,0])*(frac[:,1] if dy else 1-frac[:,1])
            np.add.at(mass,(np.clip(base[:,1]+dy,0,shape[1]-1),np.clip(base[:,0]+dx,0,shape[0]-1)),w/len(points))
    frequency=rfft2(mass);frequency=fourier_gaussian(frequency,sigma=(1/step[1],1/step[0]),n=shape[0],axis=1)
    density=np.maximum(0,irfft2(frequency,s=mass.shape)/(step[0]*step[1]))
    def evaluate(q):
        xy=(q-lo)/step
        return map_coordinates(density,[xy[:,1],xy[:,0]],order=1,mode='constant',cval=0.)
    return evaluate,{'fine_grid':shape,'fine_grid_step':step.tolist(),'deposition':'bilinear, all records; duplicate mass conserved','tail_extension_bandwidth_sd':8}

def hexbin(x,y,gridsize=42):
    x,y=np.asarray(x,float),np.asarray(y,float);mask=np.isfinite(x)&np.isfinite(y);a,b=x[mask],y[mask]
    membership=np.full(len(x),-1,dtype=np.int32)
    if not len(a):return {'bins':[],'n':0,'mask':mask,'membership':membership,'gridsize':gridsize}
    xmin,xmax=float(a.min()),float(a.max());ymin,ymax=float(b.min()),float(b.max());dx=xmax-xmin or max(abs(xmin)*.01,1.);dy=ymax-ymin or max(abs(ymin)*.01,1.)
    r=1/gridsize;u=(a-xmin)/dx;v=.7*(b-ymin)/dy
    q=2*u/(3*r);s=(-u/3+np.sqrt(3)*v/3)/r;t=-q-s
    rq,rs,rt=np.rint(q),np.rint(s),np.rint(t);err=np.column_stack([abs(rq-q),abs(rs-s),abs(rt-t)]);largest=np.argmax(err,axis=1)
    rq[largest==0]=-rs[largest==0]-rt[largest==0];rs[largest==1]=-rq[largest==1]-rt[largest==1]
    keys,inv,counts=np.unique(np.column_stack([rq,rs]).astype(np.int32),axis=0,return_inverse=True,return_counts=True);membership[mask]=inv
    angle=np.arange(6)*np.pi/3;bins=[]
    for j,((cq,cs),count) in enumerate(zip(keys,counts)):
        cx=r*1.5*cq;cy=r*np.sqrt(3)*(cs+cq/2)
        vertices=np.column_stack([xmin+(cx+r*np.cos(angle))*dx,ymin+(cy+r*np.sin(angle))*dy/.7])
        bins.append({'bin_id':f'{int(cq)}:{int(cs)}','index':j,'center':[float(xmin+cx*dx),float(ymin+cy*dy/.7)],'polygon':vertices.tolist(),'count':int(count)})
    assert sum(z['count'] for z in bins)==int(mask.sum())
    return {'bins':bins,'n':int(mask.sum()),'range':[xmin,xmax,ymin,ymax],'gridsize':gridsize,'membership':membership,'mask':mask,'color_transform':'log1p(count)'}

def kde2(x,y):
    x,y=np.asarray(x,float),np.asarray(y,float);good=np.isfinite(x)&np.isfinite(y);a=np.column_stack([x[good],y[good]])
    if len(a)<3 or np.linalg.matrix_rank(a-a.mean(0),tol=1e-12)<2:return {'status':'unavailable','reason':'rank_lt_two','n':len(a),'paths':[]}
    bandwidth=len(a)**(-1/6);cov=np.cov(a,rowvar=False)*bandwidth**2;L=np.linalg.cholesky(cov);center=a.mean(0);whitened=np.linalg.solve(L,(a-center).T).T
    model=KernelDensity(bandwidth=1.,algorithm='ball_tree',rtol=1e-7,atol=1e-12).fit(whitened);jac=np.linalg.det(L)
    fast,evaluation=_fft_evaluator(whitened);evaluation['max_observed_error_relative_to_peak']=0.;evaluation['validation_points']=0
    sd=np.sqrt(np.diag(cov));lo=a.min(0)-5*sd;hi=a.max(0)+5*sd
    previous=None;history=[];paths=[]
    for size in [128,256,512,1024]:
        xs=np.linspace(lo[0],hi[0],size);ys=np.linspace(lo[1],hi[1],size);xx,yy=np.meshgrid(xs,ys);pts=np.column_stack([xx.ravel(),yy.ravel()]);white_query=np.linalg.solve(L,(pts-center).T).T;estimate=fast(white_query)
        check=np.unique(np.r_[np.linspace(0,len(pts)-1,129,dtype=int),np.argpartition(estimate,-min(16,len(estimate)))[-16:]])
        exact=np.exp(model.score_samples(white_query[check]));relative=float(np.max(abs(exact-estimate[check]))/max(np.max(exact),1e-30))
        evaluation['max_observed_error_relative_to_peak']=max(evaluation['max_observed_error_relative_to_peak'],relative);evaluation['validation_points']+=len(check)
        if relative>.001:
            estimate=np.exp(model.score_samples(white_query));evaluation['fallback']='direct_all-record_tree_evaluation'
        z=estimate/jac
        z=z.reshape(size,size);cell=(xs[1]-xs[0])*(ys[1]-ys[0]);total=float(np.trapezoid(np.trapezoid(z,xs,axis=1),ys));flat=np.sort(z.ravel())[::-1];mass=np.cumsum(flat)*cell
        levels=[float(flat[min(np.searchsorted(mass,p),len(flat)-1)]) for p in [.5,.8,.95]]
        region_masses=[float(z[z>=level].sum()*cell) for level in levels]
        delta=max(abs(np.array(region_masses)-previous)) if previous is not None else None
        history.append({'grid':size,'integral':total,'region_mass':region_masses,'change':delta})
        if abs(total-1)<=.005 and previous is not None and delta<=.01:break
        previous=np.array(region_masses)
    generator=contourpy.contour_generator(x=xs,y=ys,z=z)
    for probability,level in zip([.5,.8,.95],levels):
        paths.append({'mass':probability,'threshold':level,'paths':[p.tolist() for p in generator.lines(level)]})
    converged=abs(total-1)<=.005 and history[-1]['change'] is not None and history[-1]['change']<=.01
    return {'status':'available' if converged else 'partial','reason':None if converged else 'grid_convergence_tolerance','n':len(a),'paths':paths,'grid':size,'integral':total,'history':history,'bandwidth_factor':bandwidth,'bandwidth_covariance':cov.tolist(),'rule':'Scott','evaluation':evaluation,'validation_reference_rtol':1e-7,'validation_reference_atol':1e-12}
