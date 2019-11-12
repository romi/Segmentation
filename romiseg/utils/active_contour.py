import cv2
import numpy as np
import matplotlib.pyplot as pl
import glob
import json
 
def exgreen(im_BGR, cvtype=False):
   Ms=np.max(im_BGR,axis=(0,1)).astype(np.float) 
   im_Norm=im_BGR/Ms
   L=im_Norm.sum(axis=2)
   res = 3*im_Norm[:,:,1]/L-1
   if cvtype:
      M=res.max()
      m=res.min()
      res = (255*(res-m)/(M-m)).astype(np.uint8)
   return res
 
def fillNpoints(xy,Np):
   ts=np.linspace(0,len(xy[0]),num=len(xy[0]),endpoint=True)
   nts=np.linspace(0,len(xy[0]),num=Np,endpoint=True)
   fx = np.interp(nts,ts, xy[0])
   fy = np.interp(nts,ts, xy[1])
   return np.array([fx,fy])
 
def getEdgeGrad(im,sig):
   im=cv2.GaussianBlur(im,(17,17),sig)    
   sc_x=cv2.Scharr(im,cv2.CV_64F,1,0)
   sc_y=cv2.Scharr(im,cv2.CV_64F,0,1)
   F_norm = np.sqrt(sc_x**2 +sc_y**2) 
   F_norm = ((F_norm-F_norm.min()) / (F_norm.max()-F_norm.min()))
   F_norm_xy = np.array(np.gradient(F_norm))
   return F_norm_xy
 
def closeCont(cont,d):
   cont_=np.vstack([cont,cont[0]]).T
   Ns=np.sqrt(np.sum(np.diff(cont_,axis=1)**2,axis=0)).astype(np.int)
   Ns = Ns/d
 
   k=0
   xys=fillNpoints(cont_[:,k:k+2],Ns[k]).T
 
   for k in range(1,len(cont_[0])-1):
      xys=np.vstack((xys,fillNpoints(cont_[:,k:k+2],Ns[k]).T))
   return xys
 
def getIntrinsic(alpha, beta, tau, k):
   Ac=np.hstack([[beta, -alpha-4*beta, 2*alpha+6*beta,-alpha-4*beta, beta],np.zeros(k-5)])
 
   A=np.zeros([k,k])
   for i in range(k):
      A[i]=np.roll(Ac,i-2)
 
   mat=np.linalg.inv(np.eye(k)+tau*A)
   return mat
 
def refine_anim(f, svgdir, beta=.0001, alpha=.01, tau=10, Nit=10000, ksave=100):
   im=cv2.imread(f+".png").astype(np.float)
   h=im.shape[0]
   w=im.shape[1]
   cidx=exgreen(im)
   M=cidx.max()
   m=cidx.min()
   imG= (255*(cidx-m)/(M-m)).astype(np.uint8)
 
   sig=3
   F_norm_xy=getEdgeGrad(imG, sig)
 
   cont=np.loadtxt(f+".txt")
   xys=closeCont(cont,d)
   intr=getIntrinsic(alpha,beta,len(xys))
   xs=xys[:,0].clip(0,w).astype(np.int)
   ys=xys[:,1].clip(0,h).astype(np.int)
   cont_hist=[[xs,ys]]
    
   pl.imshow(cv2.cvtColor(im.astype(np.uint8), cv2.COLOR_BGR2RGB))
   pl.plot(xs,ys,"b")
 
   for i in range(Nit):
      F=np.array([F_norm_xy[1,ys,xs],F_norm_xy[0,ys,xs]]).T
      xys=np.dot(intr,xys+tau*F)
      xs=xys[:,0].clip(0,w).astype(np.int)
      ys=xys[:,1].clip(0,h).astype(np.int)
      if not(i%ksave): 
         print(i)
         cont_hist.append([xs,ys])
   np.save(svgdir+'/'+f.strip("data/annotations/")+"_cont",cont_hist)   
 
   pl.plot(xs,ys,"r")
   pl.savefig(svgdir+'/'+f.strip("data/annotations/")+"_cont.jpg")
   pl.clf()
 
def refine(imname, xys=[], beta=.0001, alpha=.01, tau=10, d=1,Nit=10000, ksave=100):
   im=cv2.imread(imname).astype(np.float)
   h, w=im.shape[:2]
   imG=exgreen(im, True)
 
   sig=3
   F_norm_xy=getEdgeGrad(imG, sig)
 
   intr=getIntrinsic(alpha,beta, tau,len(xys))
    
   for i in range(Nit):
      xs=xys[:,0].clip(0,w-1).astype(np.int)
      ys=xys[:,1].clip(0,h-1).astype(np.int)
      F=np.array([F_norm_xy[1,ys,xs],F_norm_xy[0,ys,xs]]).T
      xys=np.dot(intr,xys+tau*F)

   return xs, ys
 

def run_refine0(f, beta, alpha, tau, d, Nit, plotit=None, saveit=None):
  polys = json.load(open(f[:-4] + '.json'))['shapes']
  ps=[np.array(p['points']) for p in polys]
  labels = [p['label'] for p in polys]
  label_color = {'background':0, 'flower': 51, 'peduncle': 102, 'stem' : 153, 'leaf': 204, 'fruit': 255}

  im=cv2.imread(f)
  im = im * 0
#  if plotit: cv2.polylines(im, ps, True, (242,240,218), thickness=10)
  conts=[]
  for i, p in enumerate(ps):
     init_cont = closeCont(p, 1)
     color = label_color[labels[i]]
     print(color)
     xys=refine(f, init_cont, beta, alpha, tau, d, Nit, ksave=1)
     if plotit: cv2.fillPoly(im, [np.array([xys]).astype(np.int).T], color)
     conts.append(xys)
  if True: 
      cv2.imwrite(plotit,im)
  
  if saveit: np.save(saveit,conts)
  return conts


import romiseg.utils.alienlab as alien
#g = alien.showclass()
#g.save_im = False
def run_refine(f, beta, alpha, tau, d, Nit, plotit=None):
    polys = json.load(open(f[:-4] + '.json'))['shapes']
    ps=np.array([np.array(p['points']) for p in polys])
    labels = np.array([p['label'] for p in polys])
    label_color = {'background':0, 'flower': 1, 'peduncle': 2, 'stem' :4 , 'leaf': 8, 'fruit': 16}
    num_labels = len(label_color)
    keys = list(label_color.keys())
      
    im = cv2.imread(f)
    im = im * 0
    all_im = [im*0] * num_labels #one per label
    #  if plotit: cv2.polylines(im, ps, True, (242,240,218), thickness=10)
    for i, k in enumerate(keys):
        points = ps[labels == k]
        im = im * 0
        for p in points:
            init_cont = closeCont(p, 1)
            color = label_color[k]      
            xys = refine(f, init_cont, beta, alpha, tau, d, Nit, ksave=1)
            cv2.fillPoly(im, [np.array([xys]).astype(np.int).T], color)
        cv2.imwrite(plotit, im)
        #g.showing(im[:,:,0], showit = True)
        all_im[i] = cv2.imread(plotit)
    im = sum(all_im)
    cv2.imwrite(plotit, im)
              
         


        